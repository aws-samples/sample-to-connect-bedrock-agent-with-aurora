import json
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_bedrock as bedrock,
    Duration,
    CfnOutput,
)
from constructs import Construct


class BedrockAgentStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cluster_arn = cdk.Fn.import_value("ClusterARN")
        secret_arn = cdk.Fn.import_value("ReadOnlySecretARN")
        db_name = cdk.Fn.import_value("DBName")
        model_id = (
            self.node.try_get_context("model_id")
            or "us.anthropic.claude-3-sonnet-20240229-v1:0"
        )

        # Use system-defined inference profile
        inference_profile_arn = f"arn:aws:bedrock:{Stack.of(self).region}:{Stack.of(self).account}:inference-profile/us.{model_id}"

        # Create IAM role for Lambda
        generate_query_lambda_role = iam.Role(
            self,
            "GenerateQueryLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Role for generate_query Lambda",
        )

        # add permission to generate_query_lambda_role to invoke bedrock models
        generate_query_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{Stack.of(self).region}::foundation-model/*"
                ],
            )
        )

        # Add policies to the role
        generate_query_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaVPCAccessExecutionRole"
            )
        )

        generate_query_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement"],
                resources=[cluster_arn],
            )
        )
        generate_query_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[secret_arn],
            )
        )

        # Create Lambda function
        generate_query_lambda = lambda_.Function(
            self,
            "GenerateAndExecuteQueryFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("lambda/action_group"),
            timeout=Duration.seconds(30),
            environment={
                "READONLY_SECRET_ARN": secret_arn,
                "DB_NAME": db_name,
                "CLUSTER_ARN": cluster_arn,
                "model_id": model_id,
            },
            role=generate_query_lambda_role,
        )

        # Add resource policy to allow Bedrock Agent to invoke the Lambda function
        generate_query_lambda.add_permission(
            "BedrockAgentInvokePermission",
            principal=iam.ServicePrincipal("bedrock.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_account=Stack.of(self).account,
            source_arn=f"arn:aws:bedrock:{Stack.of(self).region}:{Stack.of(self).account}:agent/*",
        )

        # Create IAM role for Bedrock Agent
        agent_role = iam.Role(
            self,
            "BedrockAgentRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for Bedrock Agent to invoke Lambda functions",
        )

        # Add trust policy with conditions
        agent_role.assume_role_policy.add_statements(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("bedrock.amazonaws.com")],
                actions=["sts:AssumeRole"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": Stack.of(self).account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock:{Stack.of(self).region}:{Stack.of(self).account}:agent/*"
                    },
                },
            )
        )

        # Add permission to invoke Model and Inference Profiles
        invoke_model_policy = agent_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            )
        )

        # Add permission to invoke the Lambda function
        invoke_lambda_policy = agent_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[generate_query_lambda.function_arn],
            )
        )

        # Create Guardrail
        guardrail = bedrock.CfnGuardrail(
            self,
            "QueryGuardrail",
            name="query-protection-guardrail",
            description="Prevents data modification attempts and harmful content",
            blocked_input_messaging="Data modification operations are not allowed. Please use SELECT queries only.",
            blocked_outputs_messaging="I cannot help with data modification. I can only help you query and retrieve data.",
            # Topic policy for data modification
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="Data Modification",
                        type="DENY",
                        definition="Attempts to modify database data",
                        examples=[
                            "insert into table",
                            "update records",
                            "delete from table",
                            "drop table",
                            "truncate table",
                        ],
                    )
                ]
            ),
            # Word policy for SQL commands
            word_policy_config=bedrock.CfnGuardrail.WordPolicyConfigProperty(
                words_config=[
                    bedrock.CfnGuardrail.WordConfigProperty(text="INSERT"),
                    bedrock.CfnGuardrail.WordConfigProperty(text="UPDATE"),
                    bedrock.CfnGuardrail.WordConfigProperty(text="DELETE"),
                    bedrock.CfnGuardrail.WordConfigProperty(text="DROP"),
                    bedrock.CfnGuardrail.WordConfigProperty(text="TRUNCATE"),
                ],
            ),
        )

        # Create Guardrail Version
        guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            "QueryGuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description="Initial version of query protection guardrail",
        )

        # Define OpenAPI schemas as raw strings to preserve formatting
        generate_api_schema = """
{
    "openapi": "3.0.0",
    "info": {
        "title": "Query Generator API",
        "version": "1.0.0",
        "description": "Query Generator API"
    },
    "paths": {
        "/generate": {
            "post": {
                "operationId": "generateQuery",
                "summary": "Generate SQL query from prompt",
                "description": "Generate SQL query from prompt",
                "requestBody": {
                    "required": "true",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["prompt"],
                                "properties": {
                                    "prompt": {
                                        "type": "string",
                                        "description": "Natural language prompt for query generation"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Generated SQL query",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}}
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
        """

        execute_api_schema = """
{
    "openapi": "3.0.0",
    "info": {
        "title": "Query Executor API",
        "version": "1.0.0",
        "description": "Query Executor API"
    },
    "paths": {
        "/execute": {
            "post": {
                "operationId": "executeQuery",
                "summary": "Execute SQL query",
                "description": "Execute SQL query",
                "requestBody": {
                    "required": "true",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "SQL query to execute"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Query results",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "results": {
                                            "type": "array",
                                            "items": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
        """

        # Add permission to Apply Bedrock Guardrail
        apply_guardrail_policy = agent_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:ApplyGuardrail"],
                resources=[
                    f"arn:aws:bedrock:{Stack.of(self).region}:{Stack.of(self).account}:guardrail/{guardrail.attr_guardrail_id}",
                ],
            )
        )

        # Create Bedrock Agent
        agent = bedrock.CfnAgent(
            self,
            "QueryAgent",
            agent_name="query-agent",
            agent_resource_role_arn=agent_role.role_arn,
            foundation_model=inference_profile_arn,
            instruction=" You are a SQL query assistant that helps users interact with a PostgreSQL database. You can generate read only (SELECT) SQL queries based on natural language prompts and execute queries against the database. Do not generate SQL queries that can modify or update any underlying data or schema in the database. Always validate queries for security before execution. Use the generate-query action to create SQL queries and the execute-query action to run them.",
            description="SQL Query Assistant for PostgreSQL Database",
            idle_session_ttl_in_seconds=1800,
            guardrail_configuration=bedrock.CfnAgent.GuardrailConfigurationProperty(
                guardrail_identifier=guardrail.attr_guardrail_id,
                guardrail_version=guardrail_version.attr_version,
            ),
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="generate-query",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=generate_query_lambda.function_arn
                    ),
                    description="Generates SQL queries from natural language prompts",
                    action_group_state="ENABLED",
                    api_schema=bedrock.CfnAgent.APISchemaProperty(
                        payload=generate_api_schema
                    ),
                ),
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="execute-query",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=generate_query_lambda.function_arn
                    ),
                    description="Executes SQL queries against the database",
                    action_group_state="ENABLED",
                    api_schema=bedrock.CfnAgent.APISchemaProperty(
                        payload=execute_api_schema
                    ),
                ),
            ],
        )
        agent.node.add_dependency(generate_query_lambda)

        # Create agent alias
        agent_alias = bedrock.CfnAgentAlias(
            self,
            "QueryAgentAlias",
            agent_alias_name="prod",
            agent_id=agent.ref,
        )

        # Outputs
        CfnOutput(self, "AgentId", value=agent.ref)
        CfnOutput(self, "AgentAliasId", value=agent_alias.ref)
        CfnOutput(self, "InferenceProfileArn", value=inference_profile_arn)
