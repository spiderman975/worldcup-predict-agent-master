import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Input, Space, Spin, Tag } from "antd";
import { CloseOutlined, DownOutlined, MessageOutlined, SendOutlined, UpOutlined } from "@ant-design/icons";

import { connectChatStream, createChatSession, sendChatMessage, startChatPrediction, type ChatMessage } from "../api/chatApi";
import { usePredictionStore } from "../stores/predictionStore";

interface ChatPanelProps {
  visible: boolean;
  onClose: () => void;
}

interface ReasoningStep {
  message: string;
  stage: string;
  status: string;
  timestamp: string;
}

interface SourceTraceItem {
  title: string;
  source: string;
  url: string;
  date?: string;
  source_type?: string;
  credibility_score?: number;
  credibility_label?: string;
  cross_check_count?: number;
  trace_note?: string;
  summary?: string;
}

interface SourceTrace {
  query?: string;
  source_count?: number;
  average_credibility?: number;
  cross_validated_count?: number;
  high_quality_count?: number;
  source_tracing_queries?: string[];
  assessment?: string;
  sources?: SourceTraceItem[];
}

const PHASE_LABELS: Record<string, string> = {
  START: "启动",
  DATA_LOADING: "数据",
  TEAM_RATING: "评分",
  GROUP_STAGE: "小组赛",
  KNOCKOUT: "淘汰赛",
  PROBABILITY: "概率",
  REASONING: "推理",
  VERIFY: "验证",
  COMPLETED: "完成",
};

function eventMessage(event: string, data: Record<string, unknown>) {
  const nested = (data.data ?? {}) as Record<string, unknown>;
  const phase = String(data.phase ?? nested.phase ?? "");
  const label = PHASE_LABELS[phase] ?? event;
  const message = String(data.message ?? nested.message ?? "");
  return `${label}: ${message || event}`;
}

export function ChatPanel({ visible, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [thinkingText, setThinkingText] = useState("Agent 正在思考...");
  const [forceWebSearch, setForceWebSearch] = useState(false);
  const [reasoningSteps, setReasoningSteps] = useState<ReasoningStep[]>([]);
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const [reasoningStartedAt, setReasoningStartedAt] = useState<number | null>(null);
  const [reasoningElapsed, setReasoningElapsed] = useState(0);
  const [sourceTrace, setSourceTrace] = useState<SourceTrace | null>(null);
  const [sourceTraceExpanded, setSourceTraceExpanded] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const connectedRunRef = useRef<string | null>(null);

  const openSession = useCallback(async () => {
    if (sessionId || initializing) return;
    setInitializing(true);
    setSessionError(null);
    try {
      const res = await createChatSession();
      setSessionId(res.session_id);
      const source = connectChatStream(
        res.session_id,
        (event, data) => {
          if (event === "user_message" || event === "agent_message" || event === "system_message") {
            setMessages((prev) => [...prev, data as unknown as ChatMessage]);
            if (event !== "user_message") setStreaming(false);
            return;
          }
          if (event === "agent_status") {
            const message = String(data.message ?? "Agent 正在思考...");
            if (!reasoningStartedAt) setReasoningStartedAt(Date.now());
            setThinkingText(message);
            setReasoningSteps((prev) => [
              ...prev,
              {
                message,
                stage: "status",
                status: "running",
                timestamp: String(data.timestamp ?? new Date().toISOString()),
              },
            ].slice(-12));
            setStreaming(true);
            return;
          }
          if (event === "agent_progress") {
            const message = String(data.message ?? "");
            if (message) {
              setReasoningSteps((prev) => [
                ...prev,
                {
                  message,
                  stage: String(data.stage ?? data.tool ?? "progress"),
                  status: String(data.status ?? "running"),
                  timestamp: String(data.timestamp ?? new Date().toISOString()),
                },
              ].slice(-12));
            }
            setThinkingText(message || "Agent 正在处理...");
            setStreaming(true);
            return;
          }
          if (event === "source_trace") {
            setSourceTrace(data as unknown as SourceTrace);
            setSourceTraceExpanded(false);
            return;
          }
          if (event === "agent_token") {
            setMessages((prev) => {
              const token = String(data.token ?? "");
              const last = prev[prev.length - 1];
              if (last?.role === "agent" && !last._done) {
                return [...prev.slice(0, -1), { ...last, content: `${last.content}${token}` }];
              }
              return [
                ...prev,
                {
                  role: "agent",
                  content: token,
                  timestamp: String(data.timestamp ?? new Date().toISOString()),
                  _done: false,
                },
              ];
            });
            return;
          }
          if (event === "agent_done") {
            setMessages((prev) => {
              const content = String(data.content ?? "");
              const last = prev[prev.length - 1];
              if (last?.role === "agent" && !last._done) {
                return [...prev.slice(0, -1), { ...last, content, _done: true }];
              }
              return [
                ...prev,
                {
                  role: "agent",
                  content,
                  timestamp: String(data.timestamp ?? new Date().toISOString()),
                  _done: true,
                },
              ];
            });
            setStreaming(false);
            if (reasoningStartedAt) {
              setReasoningElapsed(Math.max(1, Math.round((Date.now() - reasoningStartedAt) / 1000)));
            }
            setReasoningSteps((prev) => [
              ...prev,
              {
                message: "已整理完成，生成最终回答。",
                stage: "final",
                status: "completed",
                timestamp: String(data.timestamp ?? new Date().toISOString()),
              },
            ].slice(-12));
            setThinkingText("Agent 正在思考...");
            return;
          }
          if (event === "agent_error") {
            setMessages((prev) => [
              ...prev,
              { role: "system", content: `错误: ${String(data.error ?? "Agent failed")}`, timestamp: new Date().toISOString() },
            ]);
            setStreaming(false);
            return;
          }
          const nested = (data.data ?? {}) as Record<string, unknown>;
          const runId = data.run_id ?? nested.run_id;
          if (event === "prediction_start" && runId && connectedRunRef.current !== runId) {
            connectedRunRef.current = String(runId);
            const store = usePredictionStore.getState();
            store.reset();
            store.connectStream(String(runId));
          }
          if (
            event.startsWith("prediction_") ||
            event === "data_loaded" ||
            event === "team_rating_complete" ||
            event === "group_prediction" ||
            event === "bracket_update" ||
            event === "champion_probability" ||
            event === "reasoning" ||
            event === "verify"
          ) {
            setMessages((prev) => [
              ...prev,
              {
                role: event === "reasoning" ? "agent" : "system",
                content:
                  event === "reasoning" && (data.final_reasoning || nested.final_reasoning)
                    ? String(data.final_reasoning ?? nested.final_reasoning)
                    : eventMessage(event, data),
                timestamp: new Date().toISOString(),
                phase: String(data.phase ?? nested.phase ?? ""),
              },
            ]);
            if (event === "prediction_complete" || event === "prediction_error" || event === "prediction_canceled") {
              setStreaming(false);
            }
          }
        },
        () => {
          setSessionError("Agent 事件流连接异常，请确认 FastAPI 后端仍在运行。");
        },
      );
      sourceRef.current = source;
    } catch {
      setSessionError("无法连接 Agent 后端，请先启动 FastAPI。");
    } finally {
      setInitializing(false);
    }
  }, [initializing, sessionId]);

  useEffect(() => {
    if (!visible || sessionId) return;
    void openSession();
  }, [openSession, visible, sessionId]);

  useEffect(() => {
    if (!visible && sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
      setSessionId(null);
      setSessionError(null);
      setInitializing(false);
      setStreaming(false);
    }
  }, [visible]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  useEffect(() => {
    if (!reasoningStartedAt || !streaming) return;
    const timer = window.setInterval(() => {
      setReasoningElapsed(Math.max(1, Math.round((Date.now() - reasoningStartedAt) / 1000)));
    }, 500);
    return () => window.clearInterval(timer);
  }, [reasoningStartedAt, streaming]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || !sessionId || streaming || initializing) return;
    const text = inputValue.trim();
    setInputValue("");
    const startedAt = Date.now();
    setReasoningStartedAt(startedAt);
    setReasoningElapsed(0);
    setReasoningExpanded(false);
    setSourceTrace(null);
    setSourceTraceExpanded(false);
    setReasoningSteps([
      {
        message: "已收到问题，正在进入分析流程。",
        stage: "received",
        status: "running",
        timestamp: new Date(startedAt).toISOString(),
      },
    ]);
    setThinkingText(forceWebSearch ? "实时搜索已开启，Agent 正在联网核验..." : "Agent 正在接收问题...");
    setStreaming(true);
    try {
      await sendChatMessage(sessionId, text, { forceWebSearch });
    } catch {
      setMessages((prev) => [...prev, { role: "system", content: "发送失败", timestamp: new Date().toISOString() }]);
      setStreaming(false);
    }
  }, [inputValue, sessionId, streaming, initializing, forceWebSearch]);

  const handleStartPrediction = useCallback(async () => {
    if (!sessionId || streaming || initializing) return;
    const startedAt = Date.now();
    setReasoningStartedAt(startedAt);
    setReasoningElapsed(0);
    setReasoningExpanded(false);
    setReasoningSteps([
      {
        message: "已触发预测流程，正在准备任务。",
        stage: "prediction",
        status: "running",
        timestamp: new Date(startedAt).toISOString(),
      },
    ]);
    setThinkingText("Agent 正在启动预测工作流...");
    setStreaming(true);
    try {
      await startChatPrediction(sessionId, 1000);
    } catch {
      setMessages((prev) => [...prev, { role: "system", content: "启动完整冠军预测失败", timestamp: new Date().toISOString() }]);
      setStreaming(false);
    }
  }, [sessionId, streaming, initializing]);

  const inputDisabled = streaming || initializing || !sessionId;
  const lastMessage = messages[messages.length - 1];
  const answerAfterReasoning = Boolean(reasoningSteps.length > 0 && lastMessage?.role === "agent");
  const visibleMessages = answerAfterReasoning ? messages.slice(0, -1) : messages;
  const finalAnswerMessage = answerAfterReasoning ? lastMessage : null;
  const reasoningTitle = `${streaming ? "思考中" : "已思考"}${reasoningElapsed > 0 ? `（用时 ${reasoningElapsed} 秒）` : ""}`;

  const renderMessage = (msg: ChatMessage, index: number) => (
    <div key={`${msg.timestamp}-${index}`} className={`chatBubble chatBubble--${msg.role}`}>
      {msg.role === "system" ? (
        <div className="chatSystemMsg">
          {msg.phase && <Tag color="blue">{PHASE_LABELS[msg.phase] ?? msg.phase}</Tag>}
          <span>{msg.content}</span>
        </div>
      ) : (
        <>
          <div className="chatRoleLabel">{msg.role === "user" ? "你" : "Agent"}</div>
          <div className="chatContent">{msg.content}</div>
        </>
      )}
    </div>
  );

  return (
    <Drawer
      title={
        <Space>
          <MessageOutlined />
          <span>WorldCup Agent</span>
          {sessionId && <Tag color="green">已连接</Tag>}
          {initializing && <Tag color="processing">连接中</Tag>}
          {sessionError && !sessionId && <Tag color="red">未连接</Tag>}
        </Space>
      }
      placement="right"
      width={460}
      open={visible}
      onClose={onClose}
      closeIcon={<CloseOutlined />}
      styles={{ body: { padding: 0, display: "flex", flexDirection: "column" } }}
    >
      <div className="chatMessages">
        {messages.length === 0 && (
          <div className="chatEmpty">
            <p>我是世界杯预测主 Agent，可以查赛程、球队、已保存预测，也可以触发单场预测工作流。</p>
            <p>试试：今天比赛安排、预测 s4_france_spain 比分、France vs Spain 谁赢。</p>
            {sessionError && (
              <Alert
                type="error"
                showIcon
                message={sessionError}
                action={
                  <Button size="small" type="primary" onClick={openSession} loading={initializing}>
                    重连
                  </Button>
                }
              />
            )}
          </div>
        )}
        {visibleMessages.map(renderMessage)}
        {reasoningSteps.length > 0 && (
          <div className={`chatReasoningPanel ${reasoningExpanded ? "chatReasoningPanel--expanded" : ""}`}>
            <div className="chatReasoningHeader">
              {streaming ? <Spin size="small" /> : <span className="chatReasoningDot chatReasoningDot--completed" />}
              <span>{reasoningTitle}</span>
              <Tag color={streaming ? "processing" : "green"}>{streaming ? "进行中" : "已完成"}</Tag>
              <Button
                type="text"
                size="small"
                className="chatReasoningToggle"
                icon={reasoningExpanded ? <UpOutlined /> : <DownOutlined />}
                onClick={() => setReasoningExpanded((value) => !value)}
              >
                {reasoningExpanded ? "收起" : "展开"}
              </Button>
            </div>
            <div className="chatReasoningSteps">
              {reasoningSteps.map((step, index) => (
                <div key={`${step.timestamp}-${index}`} className={`chatReasoningStep chatReasoningStep--${step.status}`}>
                  <span className={`chatReasoningDot chatReasoningDot--${step.status}`} />
                  <span>{step.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {finalAnswerMessage && renderMessage(finalAnswerMessage, messages.length - 1)}
        {finalAnswerMessage && forceWebSearch && sourceTrace && (
          <SourceTracePanel
            trace={sourceTrace}
            expanded={sourceTraceExpanded}
            onToggle={() => setSourceTraceExpanded((value) => !value)}
          />
        )}
        {streaming && !(messages[messages.length - 1]?.role === "agent" && !messages[messages.length - 1]?._done) && (
          <div className="chatBubble chatBubble--agent chatBubble--thinking">
            <Spin size="small" />
            <span className="chatThinking">{thinkingText}</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="chatQuickActions">
        <Button
          size="small"
          type={forceWebSearch ? "primary" : "default"}
          onClick={() => setForceWebSearch((value) => !value)}
          disabled={initializing || !sessionId}
        >
          {forceWebSearch ? "实时搜索：开" : "开启实时搜索"}
        </Button>
        <Button size="small" onClick={handleStartPrediction} disabled={inputDisabled}>
          启动完整冠军预测
        </Button>
      </div>
      <div className="chatInputArea">
        {inputDisabled && !streaming && <div className="chatInputHint">正在建立 Agent 会话，连接成功后即可输入。</div>}
        <Space.Compact style={{ width: "100%" }}>
          <Input
            placeholder="输入问题，例如：今天比赛安排"
            value={inputValue}
            onChange={(event) => setInputValue(event.target.value)}
            onPressEnter={handleSend}
            disabled={inputDisabled}
            prefix={<SendOutlined style={{ color: "#64748b" }} />}
          />
          <Button type="primary" onClick={handleSend} disabled={inputDisabled || !inputValue.trim()}>
            发送
          </Button>
        </Space.Compact>
      </div>
    </Drawer>
  );
}

function SourceTracePanel({
  trace,
  expanded,
  onToggle,
}: {
  trace: SourceTrace;
  expanded: boolean;
  onToggle: () => void;
}) {
  const sources = trace.sources ?? [];
  return (
    <div className={`sourceTracePanel ${expanded ? "sourceTracePanel--expanded" : ""}`}>
      <div className="sourceTraceHeader">
        <span>信息来源</span>
        <Tag color={sources.length ? "blue" : "default"}>{sources.length} 条</Tag>
        <Tag color={(trace.cross_validated_count ?? 0) > 0 ? "green" : "orange"}>
          交叉验证 {trace.cross_validated_count ?? 0}
        </Tag>
        <Button
          type="text"
          size="small"
          className="chatReasoningToggle"
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          onClick={onToggle}
        >
          {expanded ? "收起" : "展开"}
        </Button>
      </div>
      <p className="sourceTraceAssessment">{trace.assessment ?? "暂无来源质量评估。"}</p>
      <div className="sourceTraceList">
        {sources.length === 0 && <span className="sourceTraceEmpty">本轮没有可展示的网页来源。</span>}
        {sources.map((item, index) => (
          <a key={`${item.url}-${index}`} className="sourceTraceItem" href={item.url} target="_blank" rel="noreferrer">
            <div>
              <strong>{item.title || item.source || "网页来源"}</strong>
              <span>{item.source} · {item.credibility_label ?? "一般"} · 交叉 {item.cross_check_count ?? 1}</span>
            </div>
            {item.trace_note && <small>{item.trace_note}</small>}
          </a>
        ))}
      </div>
      {expanded && (trace.source_tracing_queries?.length ?? 0) > 0 && (
        <div className="sourceTraceQueries">
          <strong>建议追溯查询</strong>
          {trace.source_tracing_queries?.map((query) => <span key={query}>{query}</span>)}
        </div>
      )}
    </div>
  );
}
