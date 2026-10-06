import os
import boto3

S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION
)


def upload_file(file_obj, key: str, content_type: str | None = None):
    extra_args = {}

    if content_type:
        extra_args["ContentType"] = content_type

    s3.upload_fileobj(
        file_obj,
        S3_BUCKET,
        key,
        ExtraArgs=extra_args
    )

    return {
        "bucket": S3_BUCKET,
        "key": key,
    }


def download_file(key: str):
    response = s3.get_object(
        Bucket=S3_BUCKET,
        Key=key
    )

    return response["Body"].read()


def delete_file(key: str):
    s3.delete_object(
        Bucket=S3_BUCKET,
        Key=key
    )


def list_files(prefix: str = ""):
    response = s3.list_objects_v2(
        Bucket=S3_BUCKET,
        Prefix=prefix
    )

    return [
        obj["Key"]
        for obj in response.get("Contents", [])
    ]