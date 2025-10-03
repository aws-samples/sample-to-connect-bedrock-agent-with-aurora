import json
import boto3
import os
from typing import Dict, Any, Optional, Union
from enum import Enum
from dataclasses import dataclass

schema = None
bedrock_runtime = None

rds_data = boto3.client("rds-data")

CLUSTER_ARN = os.environ["CLUSTER_ARN"]
READONLY_SECRET_ARN = os.environ["READONLY_SECRET_ARN"]
DB_NAME = os.environ["DB_NAME"]


class ErrorType(Enum):
    """Enum for different types of errors"""

    MISSING_PARAMETER = ("Missing parameter", 400)
    INVALID_QUERY = ("Invalid query", 400)
    DATABASE_ERROR = ("Database error", 500)
    UNKNOWN_PATH = ("Unknown path", 404)
    SERVER_ERROR = ("Server error", 500)

    def __init__(self, message: str, status_code: int):
        self.message = message
        self.status_code = status_code


@dataclass
class ResponseData:
    """Data class for response information"""

    action_group: str
    api_path: str
    status_code: int
    body: Dict[str, Any]
    http_method: str = "POST"


class BedrockResponseBuilder:
    """Builder class for Bedrock Agent responses"""

    @staticmethod
    def build_response(data: ResponseData) -> Dict[str, Any]:
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": data.action_group,
                "apiPath": data.api_path,
                "httpMethod": data.http_method,
                "httpStatusCode": data.status_code,
                "responseBody": {"application/json": data.body},
            },
        }

    @classmethod
    def success(
        cls, action_group: str, api_path: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Builds a success response"""
        return cls.build_response(
            ResponseData(
                action_group=action_group, api_path=api_path, status_code=200, body=data
            )
        )

    @classmethod
    def error(
        cls,
        error_type: ErrorType,
        action_group: str,
        api_path: str,
        detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Builds an error response"""
        error_message = (
            f"{error_type.message}: {detail}" if detail else error_type.message
        )
        return cls.build_response(
            ResponseData(
                action_group=action_group,
                api_path=api_path,
                status_code=error_type.status_code,
                body={"error": error_message},
            )
        )


# Add function to read SQL file
def read_schema_file():
    try:
        # Get the directory where the lambda function code is located
        lambda_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(lambda_dir, "schema.sql")

        with open(schema_path, "r") as file:
            schema_content = file.read()
        return schema_content
    except Exception as e:
        print(f"Error reading schema file: {str(e)}")
        raise


def generate_message(bedrock_runtime, model_id, system_prompt, messages, max_tokens):

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
        }
    )

    response = bedrock_runtime.invoke_model(body=body, modelId=model_id)
    response_body = json.loads(response.get("body").read())

    return response_body


def invoke_llm(messages):
    model_id = os.environ["model_id"]

    response = generate_message(bedrock_runtime, model_id, "", messages, 300)

    return response


def validate_input(question):
    # Add basic input validation
    if not question or not isinstance(question, str):
        raise ValueError("Invalid input: Question must be a non-empty string")

    # Check for common SQL injection patterns
    suspicious_patterns = [
        "--;",
        "/*",
        "*/",
        "@@",
        "DROP",
        "DELETE",
        "UPDATE",
        "ALTER",
        "INSERT",
        "EXEC",
        "GRANT",
        "REVOKE",
        "TRUNCATE",
    ]

    question_lower = question.lower()
    for pattern in suspicious_patterns:
        if pattern.lower() in question_lower:
            raise ValueError("Potentially malicious input detected")

    return question


def validate_query(sql_query):
    # Basic SQL query validation
    sql_lower = sql_query.lower()

    # Check for blocked operations
    blocked_operations = [
        "drop",
        "truncate",
        "delete",
        "update",
        "alter",
        "create",
        "insert",
        "grant",
    ]

    for operation in blocked_operations:
        if operation in sql_lower:
            raise ValueError(f"Unauthorized SQL operation detected: {operation}")
            return False

    return True


def generate_query(question):
    if not schema:
        raise ValueError("Schema not initialized")

    # Validate input before processing
    validated_question = validate_input(question)
    # Construct the prompt with schema context
    contexts = f"""
    <Instructions>
        Read database schema inside the <database_schema></database_schema> tags which contains the tables and schema information to do the following:
        1. Create a syntactically correct SQL query to answer the question.
        2. Format the query to remove any new line with space and produce a single line query.
        3. Never query for all the columns from a specific table, only ask for a few relevant columns given the question.
        4. Pay attention to use only the column names that you can see in the schema description. 
        5. Be careful to not query for columns that do not exist. 
        6. Pay attention to which column is in which table. 
        7. Qualify column names with the table name when needed.
        8. Return only the sql query without any tags.
    </Instructions>
    <database_schema>{schema}</database_schema>

    <examples>
    <question>"How many users do we have?"</question>
    <sql>SELECT SUM(users) FROM customers</sql>

    <question>"How many users do we have for Mobile?"</question>
    <sql>SELECT SUM(users) FROM customer WHERE source_medium='Mobile'</sql>
    </examples>

    <question>{validated_question}</question>
    Return only the SQL query without any explanations.
    """

    prompt = f"""
    Human: Use the following pieces of context to provide a concise answer to the question at the end. If you don't know the answer, just say that you don't know, don't try to make up an answer.
    <context>
    {contexts}
    </context
    Question: {validated_question}
    Assistant:
    """

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt.format(contexts, validated_question)}
            ],
        }
    ]
    llm_response = invoke_llm(messages)

    print(llm_response)
    print(llm_response["content"][0]["text"])

    return llm_response["content"][0]["text"]


def execute_query(query, parameters=None):
    try:
        # Base request parameters
        request_params = {
            "resourceArn": CLUSTER_ARN,
            "secretArn": READONLY_SECRET_ARN,
            "database": DB_NAME,
            "sql": query,
        }

        # Only add parameters if they exist and are not empty
        if parameters and len(parameters) > 0:
            request_params["parameters"] = parameters

        # Execute the query
        response = rds_data.execute_statement(**request_params)
        return response

    except Exception as e:
        print(f"Error executing query: {str(e)}")
        raise


def handle_generate(properties, action_group):
    try:
        # Find the prompt property
        for prop in properties:
            if prop.get("name") == "prompt":
                prompt = prop.get("value")

        if not prompt:
            return BedrockResponseBuilder.error(
                ErrorType.MISSING_PARAMETER,
                action_group,
                "/generate",
                "Prompt parameter is required",
            )

        generated_query = generate_query(prompt)
        print(f"Generated query: {generated_query}")

        if not validate_query(generated_query):
            return BedrockResponseBuilder.error(
                ErrorType.INVALID_QUERY,
                action_group,
                "/generate",
                "Generated query contains forbidden operations",
            )

        return BedrockResponseBuilder.success(
            action_group, "/generate", {"query": generated_query}
        )

    except Exception as e:
        print(f"Error in generate: {str(e)}")
        return BedrockResponseBuilder.error(
            ErrorType.SERVER_ERROR, action_group, "/generate", str(e)
        )


def handle_execute(properties, action_group):
    try:
        query = None
        for prop in properties:
            if prop.get("name") == "query":
                query = prop.get("value")

        if not query:
            return BedrockResponseBuilder.error(
                ErrorType.MISSING_PARAMETER,
                action_group,
                "/execute",
                "Query parameter is required",
            )

        if not validate_query(query):
            return BedrockResponseBuilder.error(
                ErrorType.INVALID_QUERY,
                action_group,
                "/execute",
                "Query contains forbidden operations",
            )

        # Execute the query
        try:

            results = execute_query(query)

            return BedrockResponseBuilder.success(
                action_group, "/execute", {"results": results}
            )
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            return BedrockResponseBuilder.error(
                ErrorType.DATABASE_ERROR, action_group, "/execute", str(e)
            )

    except Exception as e:
        print(f"Error in execute: {str(e)}")
        return BedrockResponseBuilder.error(
            ErrorType.SERVER_ERROR, action_group, "/execute", str(e)
        )


try:
    schema = read_schema_file()
    bedrock_runtime = boto3.client("bedrock-runtime")
except Exception as e:
    print(f"Failed to initialize: {str(e)}")
    raise


def handler(event, context):
    try:
        print(event)
        request_body = event.get("requestBody", {})
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        properties = json_content.get("properties", [])
        api_path = event.get("apiPath", "")
        action_group = event.get("actionGroup", "")

        # Route to appropriate handler based on API path
        if api_path == "/generate":
            return handle_generate(properties, action_group)
        elif api_path == "/execute":
            return handle_execute(properties, action_group)
        else:
            return BedrockResponseBuilder.error(
                ErrorType.SERVER_ERROR,
                action_group,
                api_path,
                {"error": f"Unknown API path: {api_path}"},
            )

    except Exception as e:
        print("Error processing request")
        return BedrockResponseBuilder.error(
            ErrorType.SERVER_ERROR, action_group, "/execute", str(e)
        )
