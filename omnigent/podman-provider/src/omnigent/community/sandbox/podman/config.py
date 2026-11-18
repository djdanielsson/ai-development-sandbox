from pydantic import BaseModel, ConfigDict, Field


class PodmanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = Field(default="docker.io/library/omnigent-local:latest", min_length=1)
    network: str = Field(default="omnigent-net", min_length=1)
