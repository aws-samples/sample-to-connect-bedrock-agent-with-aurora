import boto3
import json
import time
import argparse


class BedrockAgentTester:
    def __init__(self):
        self.bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")
        self.agent_id = "Update with BedrockAgentStack.AgentId"
        self.agent_alias_id = "TSTALIASID"

        # Test cases
        # Single prompt
        self.single_prompt = "Show me all students and their major department names ?"

        # Multiple prompts
        self.test_cases = [
            # Basic Queries
            "How many students are enrolled in the Computer Science department?",
            "List all courses in the Physics department with their credits",
            "What is the total number of departments?",
            # Joins and Complex Queries
            "Show me all students and their major department names",
            "List all professors (employees with position 'Professor') and their departments",
            "Which buildings were constructed after 2000?",
            # Aggregations
            "What is the average funding amount for research projects?",
            "How many students are enrolled in each department?",
            "Count the number of employees by position",
            # Date-based Queries
            "List all research projects that are currently active",
            "Show me all students who enrolled in 2022",
            "Find all employees hired before 2019",
            # Multi-table Complex Queries
            "Show me the department names and their total number of courses",
            "List all buildings and the number of research projects in each",
            "Find departments with more than 2 courses",
            # Specific Data Queries
            "What courses does student John Doe take?",
            "Show me all details about the AI in Education research project",
            "Can you find the members of AI in Education project ? ",
        ]

    def invoke_agent(self, prompt, trace_enabled=False):
        """Invoke Bedrock agent and return response"""
        try:
            response = self.bedrock_agent_runtime.invoke_agent(
                agentId=self.agent_id,
                agentAliasId=self.agent_alias_id,
                sessionId=f"test-session-{int(time.time())}",
                inputText=prompt,
                enableTrace=trace_enabled,  # Enable tracing
            )

            # Extract response text
            completion = ""
            trace_info = []

            for event in response.get("completion"):
                if "chunk" in event:
                    chunk = event["chunk"]
                    # print("\n- chunk", chunk)
                    completion += chunk.get("bytes", b"").decode()
                elif "trace" in event:
                    trace = event["trace"]
                    trace_info.append(trace)
                else:
                    print("\nevent", event)

            return {
                "success": True,
                "response": completion.strip(),
                "trace": trace_info,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "trace": trace_info}

    def print_trace_steps(self, trace_entries):
        """Print minimal information for each trace step"""
        try:
            print("\n📋 Trace Steps:")
            print("=" * 80)

            for i, entry in enumerate(trace_entries, 1):
                trace_data = entry["trace"]

                # Check for orchestration trace
                if "orchestrationTrace" in trace_data:
                    orch_trace = trace_data["orchestrationTrace"]
                    if "modelInvocationOutput" in orch_trace:
                        output = orch_trace["modelInvocationOutput"]
                        if "rawResponse" in output:
                            print(f"\n⚙️ Step {i} - Orchestration:")
                            print("-" * 40)
                            print(f"Response: {output['rawResponse']['content']}")
                    elif "invocationInput" in orch_trace:
                        input = orch_trace["invocationInput"]
                        print(f"\n⚙️ Step {i} - Orchestration:")
                        print("-" * 40)
                        print(f"invocationInput: {input}")
                    elif "observation" in orch_trace:
                        observation = orch_trace["observation"]
                        print(f"\n⚙️ Step {i} - Orchestration:")
                        print("-" * 40)
                        print(f"Observation: {observation}")
                    else:
                        print(f"\n⚙️ Step {i} - Skip printing trace entry:")
                        print("-" * 40)

                # Check for preprocessing trace
                elif "preProcessingTrace" in trace_data:
                    pre_trace = trace_data["preProcessingTrace"]
                    if "modelInvocationOutput" in pre_trace:
                        output = pre_trace["modelInvocationOutput"]
                        if "rawResponse" in output:
                            print(f"\n🔍 Step {i} - Pre-processing:")
                            print("-" * 40)
                            print(f"Response: {output['rawResponse']['content']}")
                    else:
                        print(f"\n🔍 Step {i} - Skip printing trace entry:")
                        print("-" * 40)
                else:
                    print(f"\n🔍 Step {i} - Skip printing trace entry:")
                    print("-" * 40)

        except Exception as e:
            print(f"\n❌ Error printing trace: {str(e)}")
            import traceback

            traceback.print_exc()

    def run_all_tests(self, trace_enabled=False):
        """Run test cases and print results"""
        print("\nBEDROCK AGENT TEST RESULTS")
        print("=" * 50)

        for i, test in enumerate(self.test_cases, 1):
            print(f"\nTest Case {i}")
            print("-" * 50)
            print(f"Prompt: {test}")

            # Get agent response with trace
            print("\nInvoking Agent...")
            result = self.invoke_agent(test, trace_enabled)

            if result["success"]:
                print("\nAgent Response:")
                print(result["response"])

                # Print trace steps if available
                if result["trace"] and trace_enabled:
                    self.print_trace_steps(result["trace"])

            else:
                print("\n❌ Error in response:")
                print(result["error"])

            print("\n" + "=" * 50)

    def run_single_test(self, trace_enabled=False):
        """Run single test"""

        prompt = self.single_prompt

        print("\nBEDROCK AGENT TEST RESULTS")
        print("=" * 50)

        print(f"\nSingle Test")
        print("-" * 50)
        print(f"Prompt: {prompt}")

        # Get agent response with trace
        print("\nInvoking Agent...")
        result = self.invoke_agent(prompt, trace_enabled)

        if result["success"]:
            print("\nAgent Response:")
            print(result["response"])

            # Print trace steps if available
            if result["trace"] and trace_enabled:
                self.print_trace_steps(result["trace"])

        else:
            print("\n❌ Error in response:")
            print(result["error"])

        print("\n" + "=" * 50)


def main():

    # Set up argument parser
    parser = argparse.ArgumentParser(description="Bedrock Agent Tester")
    parser.add_argument(
        "--test-type",
        choices=["single", "all"],
        default="single",
        help="Run single test or all tests",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Enable trace output",
    )

    # Parse arguments
    args = parser.parse_args()

    tester = BedrockAgentTester()

    # Run tests based on arguments
    if args.test_type == "single":
        tester.run_single_test(args.trace)
    else:
        tester.run_all_tests(args.trace)


if __name__ == "__main__":
    main()
