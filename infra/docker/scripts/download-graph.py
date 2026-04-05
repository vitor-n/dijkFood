"""Download São Paulo street graph from S3 before service startup."""
import os
import sys


def main():
    bucket = os.environ.get("S3_BUCKET")
    key = os.environ.get("S3_GRAPH_KEY")
    path = os.environ.get("GRAPH_PATH", "/data/sao_paulo.pkl")

    if not bucket or not key:
        if os.path.exists(path):
            print(f"[graph] Using local graph at {path}")
            return
        print("[graph] S3_BUCKET/S3_GRAPH_KEY not set and no local graph found", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(path):
        print(f"[graph] Graph already present at {path}, skipping download")
        return

    import boto3

    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"[graph] Downloading s3://{bucket}/{key} → {path} ...")
    boto3.client("s3").download_file(bucket, key, path)
    print("[graph] Download complete")


if __name__ == "__main__":
    main()
