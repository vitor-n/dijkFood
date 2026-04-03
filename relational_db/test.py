import boto3
from botocore.exceptions import ClientError
import psycopg2

import time

REGION         = "us-east-1"
DB_INSTANCE_ID = "food-database"
#DB_REPLICA_ID  = "rds-demo-replica"
DB_NAME        = "production"
DB_ADMIN_USER  = "admin_user_prod"
DB_PASSWORD    = "Ihateavroformat69"   # use Secrets Manager in production
DB_IAM_USER    = "demo_iam"         # created during populate; used in experiment A
DB_PORT        = 5432
INSTANCE_CLASS = "db.t3.micro"
PG_VERSION     = "16"
SG_NAME        = "rds-demo-sg"
PG_GROUP_NAME  = "rds-demo-pg16"   # custom parameter group

def get_default_vpc(ec2_client):
    vpcs = ec2_client.describe_vpcs(
        Filters=[{'Name': 'isDefault', 'Values': ['true']}]
    )
    if not vpcs["Vpcs"]:
        raise RuntimeError("No default VPC found.")
    return vpcs['Vpcs'][0]['VpcId']

#
def create_dumb_security_group(ec2_client, vpc_id):
    try:
        sg = ec2_client.create_security_group(
            GroupName = SG_NAME,
            Description = "Group that allows anyone to connect to a RDS instance",
            VpcId = vpc_id,
        )
        sg_id = sg["GroupId"]
        ec2_client.authorize_security_group_ingress(
            GroupId = sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": DB_PORT,
                "ToPort": DB_PORT,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            existing = ec2_client.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [SG_NAME]}]
            )
            sg_id = existing["SecurityGroups"][0]["GroupId"]
        else:
            raise
    return sg_id

def destroy_security_group(ec2_client, sg_id):
    try:
        sgs = ec2_client.describe_security_groups(
            Filters=[{"Name": "group-id", "Values": [sg_id]}]
        )
        if sgs["SecurityGroups"]:
            sg_name = sgs["SecurityGroups"][0]["GroupName"]
            ec2_client.delete_security_group(GroupId=sg_id)
            print(f"[SG]  {sg_id} ({sg_name}) deleted.")
    except ClientError as exc:
        print(f"[SG]  Could not delete: {exc.response['Error']['Code']}")

def allocate_rds(rds_client, sg_id, pg_group = None):
    try:
        rds_client.create_db_instance(
            DBInstanceIdentifier = DB_INSTANCE_ID,
            DBInstanceClass = INSTANCE_CLASS,
            Engine = "postgres",
            EngineVersion = PG_VERSION,
            MasterUsername = DB_ADMIN_USER,
            MasterUserPassword = DB_PASSWORD,
            DBName = DB_NAME,
            AllocatedStorage = 20,
            StorageType = "gp2",
            VpcSecurityGroupIds = [sg_id],
#            DBParameterGroupName = pg_group,
            EnableIAMDatabaseAuthentication = True,
            PubliclyAccessible = True,
            BackupRetentionPeriod = 1,   # minimum required for Read Replica
            MultiAZ = False,
            AutoMinorVersionUpgrade = False,
            Tags = [{"Key": "application", "Value": "dijkfood"},
                    {"Key": "component", "Value": "database"}],
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "DBInstanceAlreadyExists":
            print("[RDS] Already exists, skipping creation.")
        else:
            raise

    print("[RDS] Waiting for 'available' (typically 5–8 min) ...")
    waiter = rds_client.get_waiter("db_instance_available")
    waiter.wait(DBInstanceIdentifier = DB_INSTANCE_ID,
                WaiterConfig = {"Delay": 30, "MaxAttempts": 40})

    info = rds_client.describe_db_instances(DBInstanceIdentifier=DB_INSTANCE_ID)
    instance = info["DBInstances"][0]
    endpoint = instance["Endpoint"]["Address"]
    print(f"[RDS] Ready  endpoint={endpoint}  version={instance['EngineVersion']}")
    return endpoint

def destroy_rds(rds_client, db_id):
    try:
        rds_client.delete_db_instance(
            DBInstanceIdentifier = db_id,
            SkipFinalSnapshot = True,
            DeleteAutomatedBackups = True,
        )
        waiter = rds_client.get_waiter("db_instance_deleted")
        waiter.wait(DBInstanceIdentifier=db_id,
               WaiterConfig={"Delay": 30, "MaxAttempts": 40})
        print(f"[RDS] {"primary".capitalize()} deleted.")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("DBInstanceNotFound", "InvalidDBInstanceState"):
            print(f"[RDS] {"primary".capitalize()} not found or already deleted.")
        else:
            raise

    # try:
    #     rds.delete_db_parameter_group(DBParameterGroupName=PG_GROUP_NAME)
    #     print(f"[PG]  '{PG_GROUP_NAME}' deleted.")
    # except ClientError as exc:
    #     print(f"[PG]  Could not delete: {exc.response['Error']['Code']}")

def get_primary_endpoint(rds):
    info = rds.describe_db_instances(DBInstanceIdentifier=DB_INSTANCE_ID)
    return info["DBInstances"][0]["Endpoint"]["Address"]

def connect(endpoint, user=DB_ADMIN_USER, password=DB_PASSWORD,
            retries=6, delay=10, ssl=False):
    kwargs = dict(
        host=endpoint,
        port=DB_PORT,
        dbname=DB_NAME,
        user=user,
        password=password,
        connect_timeout=10
    )
    if ssl:
        kwargs["sslmode"] = "require"

    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(**kwargs)
            print(f"[DB]  Connected  host={endpoint}  user={user}")
            return conn
        except psycopg2.OperationalError as exc:
            if attempt == retries:
                raise
            print(f"[DB]  Attempt {attempt}/{retries}: {exc}. Retrying in {delay}s ...")
            time.sleep(delay)
    return None

def set_table_schema(conn):
    with conn.cursor() as cur:
        with open("database_schema.sql", "r") as file:
            DDL = file.read()
        cur.execute(DDL)

def populate_enums(conn):
    with conn.cursor() as cur:
        with open("database_enums.sql", "r") as file:
            DML = file.read()
        cur.execute(DML)


def main():
    session = boto3.Session(region_name = REGION)
    ec2_client, rds_client = session.client("ec2"), session.client("rds")

    default_vpc = get_default_vpc(ec2_client)
    sg = create_dumb_security_group(ec2_client, default_vpc)
    db_string = allocate_rds(rds_client, sg)
    print(db_string)
    endpoint = get_primary_endpoint(rds_client)
    conn = connect(endpoint)
    set_table_schema(conn)
    populate_enums(conn)
    input("Press enter to remove db")
    destroy_rds(rds_client, DB_INSTANCE_ID)
    destroy_security_group(ec2_client, sg)

if __name__ == "__main__":
    main()
