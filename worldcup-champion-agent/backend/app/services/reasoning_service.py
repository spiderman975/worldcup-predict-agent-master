from app.agent.reasoning_generator import generate_reasoning


def build_reasoning(*args, **kwargs) -> str:
    """服务层包装推理生成，便于后续接入远程大模型。"""

    return generate_reasoning(*args, **kwargs)
