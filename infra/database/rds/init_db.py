#!/usr/bin/env python3
import sys
import os
import argparse
import psycopg2

def clear_dynamodb():
    import boto3
    try:
        region = os.environ.get("AWS_REGION", "us-east-1")
        dynamodb = boto3.resource("dynamodb", region_name=region)
        table_name = os.environ.get("DYNAMO_TABLE", "CourierTracking")
        table = dynamodb.Table(table_name)
        
        print(f"Purging DynamoDB table '{table_name}'...")
        scan = None
        count = 0
        with table.batch_writer() as batch:
            while scan is None or "LastEvaluatedKey" in scan:
                if scan is not None:
                    scan = table.scan(ExclusiveStartKey=scan["LastEvaluatedKey"])
                else:
                    scan = table.scan()
                for item in scan.get("Items", []):
                    batch.delete_item(Key={"ID_courier": item["ID_courier"]})
                    count += 1
        print(f"DynamoDB table purged successfully! {count} items removed.")
    except Exception as e:
        print(f"[Warning] Failed to purge DynamoDB: {e}")

def main():
    clear_dynamodb()
    
    parser = argparse.ArgumentParser(description="Initialize dijkFood RDS database")
    parser.add_argument("--host", help="RDS database host")
    parser.add_argument("--user", help="Database user")
    parser.add_argument("--password", help="Database password")
    parser.add_argument("--dbname", default="dijkfood", help="Database name")
    
    args = parser.parse_args()
    
    host = args.host or os.environ.get("DB_HOST")
    user = args.user or os.environ.get("DB_USERNAME") or os.environ.get("DB_USER") or "dijkfood_admin"
    password = args.password or os.environ.get("DB_PASSWORD")
    dbname = args.dbname or os.environ.get("DB_NAME") or "dijkfood"
    
    if not host:
        print("[Error] Database host (--host or DB_HOST) must be specified.", file=sys.stderr)
        sys.exit(1)
        
    print(f"Connecting to database {dbname} at {host} as user {user}...")
    
    try:
        conn = psycopg2.connect(
            host=host,
            database=dbname,
            user=user,
            password=password,
            port=5432
        )
        conn.autocommit = True
        
        # Obter os scripts SQL relativos ao diretório deste script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(script_dir, "schema.sql")
        seed_path = os.path.join(script_dir, "lookup-data.sql")
        
        print(f"Reading schema from {schema_path}...")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
            
        print(f"Reading seed data from {seed_path}...")
        with open(seed_path, "r", encoding="utf-8") as f:
            seed_sql = f.read()
            
        with conn.cursor() as cursor:
            print("Executing schema.sql...")
            cursor.execute(schema_sql)
            print("Executing lookup-data.sql...")
            cursor.execute(seed_sql)
            
        conn.close()
        print("Database initialized successfully!")
        
    except Exception as e:
        print(f"[Error] Failed to initialize database: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
