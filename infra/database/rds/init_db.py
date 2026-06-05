#!/usr/bin/env python3
import sys
import os
import argparse
import psycopg2

def main():
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
