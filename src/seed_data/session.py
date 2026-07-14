"""Shared boto3 session factory for consistent AWS credential handling."""
import os
import boto3


def get_boto_session() -> boto3.Session:
    """Create a boto3 session that respects AWS_PROFILE for credential_process."""
    kwargs = {}
    if os.environ.get("AWS_PROFILE"):
        kwargs["profile_name"] = os.environ["AWS_PROFILE"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.Session(region_name=region, **kwargs)
