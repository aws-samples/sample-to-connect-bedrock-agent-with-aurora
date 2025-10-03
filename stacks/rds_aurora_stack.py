from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_secretsmanager as sm,
    CfnOutput,
    CfnDynamicReference,
    CfnDynamicReferenceService,
    custom_resources as cr,
    Fn,
    Duration,
)
from constructs import Construct
import json


class RDSAuroraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        database_name = "sample"
        engine_version = self.node.try_get_context("pg_engine_version")
        min_acu = self.node.try_get_context("min_acu")
        max_acu = self.node.try_get_context("max_acu")

        # VPC
        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    cidr_mask=24,
                    name="aurora_isolated_",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                ),
                ec2.SubnetConfiguration(
                    cidr_mask=24, name="public", subnet_type=ec2.SubnetType.PUBLIC
                ),
            ],
        )

        flow_log = vpc.add_flow_log(
            "FlowLog",
            traffic_type=ec2.FlowLogTrafficType.REJECT,
            max_aggregation_interval=ec2.FlowLogMaxAggregationInterval.ONE_MINUTE,
        )

        # Security group
        db_security_group = ec2.SecurityGroup(
            self,
            "db-security-group",
            security_group_name="db-security-group",
            description="db-security-group",
            allow_all_outbound=True,
            vpc=vpc,
        )

        # DB Subnet Group
        # subnet_ids = [subnet.subnet_id for subnet in vpc.isolated_subnets]
        subnet_ids = [subnet.subnet_id for subnet in vpc.private_subnets]

        db_subnet_group = rds.CfnDBSubnetGroup(
            self,
            "AuroraSubnetGroup",
            db_subnet_group_description="Subnet group to access aurora",
            db_subnet_group_name="aurora-serverless-subnet-group",
            subnet_ids=subnet_ids,
        )

        # Secret Manager
        secret = sm.CfnSecret(
            self,
            "AuroraGlobalServerlessDBSecret",
            name="aurora-serverless-db-secret",
            generate_secret_string=sm.CfnSecret.GenerateSecretStringProperty(
                secret_string_template='{"username": "postgres"}',
                exclude_punctuation=True,
                include_space=False,
                generate_string_key="password",
            ),
        )

        # Aurora DB Cluste
        db_cluster = rds.CfnDBCluster(
            self,
            "RDSCluster",
            db_cluster_identifier=construct_id,
            db_subnet_group_name=db_subnet_group.db_subnet_group_name,
            engine="aurora-postgresql",
            engine_version=engine_version,
            database_name=database_name,
            master_username=CfnDynamicReference(
                CfnDynamicReferenceService.SECRETS_MANAGER,
                "aurora-serverless-db-secret:SecretString:username",
            ).to_string(),
            master_user_password=CfnDynamicReference(
                CfnDynamicReferenceService.SECRETS_MANAGER,
                "aurora-serverless-db-secret:SecretString:password",
            ).to_string(),
            vpc_security_group_ids=[db_security_group.security_group_id],
            enable_http_endpoint=True,
            serverless_v2_scaling_configuration=rds.CfnDBCluster.ServerlessV2ScalingConfigurationProperty(
                min_capacity=min_acu,  # Minimum ACU value
                max_capacity=max_acu,  # Maximum ACU value
            ),
            storage_encrypted=True,
            deletion_protection=True,
        )

        db_cluster.add_dependency(db_subnet_group)
        db_cluster.add_dependency(secret)

        # Then create the serverless instance
        cfn_db_instance_props = {
            "db_cluster_identifier": db_cluster.ref,  # Use ref instead of db_cluster_identifier
            "db_instance_class": "db.serverless",
            "db_instance_identifier": "serverless-db-instance",
            "engine": "aurora-postgresql",
            "engine_version": engine_version,
        }

        db_instance = rds.CfnDBInstance(
            self, "serverless-db-instance", **cfn_db_instance_props
        )
        db_instance.add_dependency(db_cluster)

        # Construct the ARN
        cluster_arn = Fn.join(
            ":",
            [
                "arn",
                Fn.ref("AWS::Partition"),
                "rds",
                Fn.ref("AWS::Region"),
                Fn.ref("AWS::AccountId"),
                f"cluster:{db_cluster.ref}",
            ],
        )

        # Create a secret for the read-only user credentials
        readonly_credentials = sm.CfnSecret(
            self,
            "ReadOnlyUserCredentials",
            generate_secret_string=sm.CfnSecret.GenerateSecretStringProperty(
                secret_string_template='{"username": "readonly_user"}',
                generate_string_key="password",
                exclude_characters="\"@/\\ '",
                exclude_punctuation=True,
                include_space=False,
            ),
        )

        # Create the IAM role for the Lambda function
        create_user_lambda_role = iam.Role(
            self,
            "CreateReadOnlyLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for Creating Aurora PostgreSQL ReadOnly User",
        )

        # Add AWS Lambda basic execution policy
        create_user_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        # add policy for reading secretmanager
        create_user_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[readonly_credentials.attr_id, secret.attr_id],
            )
        )

        create_user_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement"],
                resources=[db_cluster.attr_db_cluster_arn],
            )
        )

        # Create Lambda function to create the read-only user
        create_user_lambda = lambda_.Function(
            self,
            "CreateReadOnlyUserHandler",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="index.handler",
            code=lambda_.Code.from_asset("lambda/custom_resource"),
            environment={
                "CLUSTER_ARN": db_cluster.attr_db_cluster_arn,
                "ADMIN_SECRET_ARN": secret.attr_id,
                "READONLY_SECRET_ARN": readonly_credentials.attr_id,
                "DB_NAME": "postgres",
            },
            role=create_user_lambda_role,
            timeout=Duration.seconds(120),
        )
        create_user_lambda.node.add_dependency(db_instance)

        create_user_custom_resource = cr.AwsCustomResource(
            self,
            "CreateReadOnlyCustomResource",
            on_create=cr.AwsSdkCall(
                service="Lambda",
                action="invoke",
                parameters={
                    "FunctionName": create_user_lambda.function_name,
                    "InvocationType": "RequestResponse",
                    "Payload": json.dumps(
                        {
                            "RequestType": "Create",
                            "StackId": self.stack_id,
                        }
                    ),
                },
                physical_resource_id=cr.PhysicalResourceId.of("ReadOnlyUserCreation"),
            ),
            on_delete=cr.AwsSdkCall(
                service="Lambda",
                action="invoke",
                parameters={
                    "FunctionName": create_user_lambda.function_name,
                    "InvocationType": "RequestResponse",
                    "Payload": json.dumps(
                        {
                            "RequestType": "Delete",
                            "StackId": self.stack_id,
                        }
                    ),
                },
                physical_resource_id=cr.PhysicalResourceId.of("ReadOnlyUsereDeletion"),
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=["lambda:InvokeFunction"],
                        resources=[create_user_lambda.function_arn],
                    )
                ]
            ),
        )
        # Ensure Custom Resource is created after the Lambda
        create_user_custom_resource.node.add_dependency(create_user_lambda)

        CfnOutput(
            self,
            "CLUSTER_ARN",
            value=db_cluster.attr_db_cluster_arn,
            export_name="ClusterARN",
        )
        CfnOutput(
            self,
            "ADMIN_SECRET_ARN",
            value=secret.attr_id,
            export_name="AdminSecretARN",
        )
        CfnOutput(
            self,
            "READONLY_SECRET_ARN",
            value=readonly_credentials.attr_id,
            export_name="ReadOnlySecretARN",
        )
        CfnOutput(self, "DB_NAME", value="postgres", export_name="DBName")
