import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Input, Space, Spin, Tag } from "antd";
import { CloseOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";

import { connectChatStream, createChatSession, sendChatMessage, startChatPrediction, type ChatMessage } from "../api/chatApi";
import { usePredictionStore } from "../stores/predictionStore";

interface ChatPanelProps {
  visible: boolean;
  onClose: () => void;
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
            setStreaming(false);
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
    }
  }, [visible]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || !sessionId || streaming || initializing) return;
    const text = inputValue.trim();
    setInputValue("");
    setStreaming(true);
    try {
      await sendChatMessage(sessionId, text);
    } catch {
      setMessages((prev) => [...prev, { role: "system", content: "发送失败", timestamp: new Date().toISOString() }]);
      setStreaming(false);
    }
  }, [inputValue, sessionId, streaming, initializing]);

  const handleStartPrediction = useCallback(async () => {
    if (!sessionId || streaming || initializing) return;
    setStreaming(true);
    try {
      await startChatPrediction(sessionId, 1000);
    } catch {
      setMessages((prev) => [...prev, { role: "system", content: "启动完整冠军预测失败", timestamp: new Date().toISOString() }]);
      setStreaming(false);
    }
  }, [sessionId, streaming, initializing]);

  const inputDisabled = streaming || initializing || !sessionId;

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
            <p>试试：预测 A1 比分、A1 为什么这么预测、Brazil vs Mexico 谁赢。</p>
            {sessionError && (
              <Alert
                type="error"
                showIcon
                message={sessionError}
                action={<Button size="small" type="primary" onClick={openSession} loading={initializing}>重连</Button>}
              />
            )}
          </div>
        )}
        {messages.map((msg, index) => (
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
        ))}
        {streaming && !(messages[messages.length - 1]?.role === "agent" && !messages[messages.length - 1]?._done) && (
          <div className="chatBubble chatBubble--agent">
            <Spin size="small" />
            <span className="chatThinking">Agent 正在处理...</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="chatQuickActions">
        <Button size="small" onClick={handleStartPrediction} disabled={inputDisabled}>
          启动完整冠军预测
        </Button>
      </div>
      <div className="chatInputArea">
        {inputDisabled && !streaming && <div className="chatInputHint">正在建立 Agent 会话，连接成功后即可输入。</div>}
        <Space.Compact style={{ width: "100%" }}>
          <Input
            placeholder="输入问题，例如：预测 A1 比分"
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
