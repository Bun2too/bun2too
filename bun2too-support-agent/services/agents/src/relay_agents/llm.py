from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel


def chat_model(spec: str) -> BaseChatModel:
    return init_chat_model(spec)


def structured[T: BaseModel](model: BaseChatModel, schema: type[T]) -> Runnable[Any, Any]:
    return model.with_structured_output(schema, method="json_schema")
