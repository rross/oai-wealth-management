import os

import asyncio
import uuid
import logging

from agents import (
    Agent,
    HandoffOutputItem,
    ItemHelpers,
    MessageOutputItem,
    RunContextWrapper,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
    TResponseInputItem,
    function_tool,
    trace,
    gen_trace_id,
)

from agents.mcp import MCPServer, MCPServerStdio

from common.account_context import AccountContext
from common.agent_constants import BENE_AGENT_NAME, BENE_HANDOFF, BENE_INSTRUCTIONS, INVEST_AGENT_NAME, INVEST_HANDOFF, \
    INVEST_INSTRUCTIONS, SUPERVISOR_AGENT_NAME, SUPERVISOR_HANDOFF, SUPERVISOR_INSTRUCTIONS
from common.beneficiaries_manager import BeneficiariesManager
from common.investment_account_manager import InvestmentAccountManager

### Logging Configuration
# logging.basicConfig(level=logging.INFO,
#                     filename="oai_supervisor.log",
#                     format="%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.info("Wealth Management Chatbot Example Starting")

### Managers

investment_acct_mgr = InvestmentAccountManager()
beneficiaries_mgr = BeneficiariesManager()

### Tools

@function_tool
async def add_beneficiaries(
        context: RunContextWrapper[AccountContext], account_id: str,
        first_name: str, last_name: str, relationship: str
):
    context.context.account_id = account_id
    beneficiaries_mgr.add_beneficiary(account_id, first_name, last_name, relationship)

@function_tool
async def list_beneficiaries(
        context: RunContextWrapper[AccountContext], account_id: str
) -> list:
    """
    List the beneficiaries for the given account id.

    Args:
        account_id: The customer's account id
    """
    # update the context
    context.context.account_id = account_id
    return beneficiaries_mgr.list_beneficiaries(account_id)

@function_tool
async def delete_beneficiaries(
        context: RunContextWrapper[AccountContext], account_id: str, beneficiary_id: str
):
        context.context.account_id = account_id
        logger.info(f"Tool: Deleting beneficiary {beneficiary_id} from account {account_id}")
        beneficiaries_mgr.delete_beneficiary(account_id, beneficiary_id)


@function_tool
async def open_investment(context: RunContextWrapper[AccountContext], account_id: str, name: str, balance: str):
    context.context.account_id = account_id
    investment_acct_mgr.add_investment_account(account_id, name, balance)

@function_tool
async def list_investments(
        context: RunContextWrapper[AccountContext], account_id: str
) -> dict:
    """
    List the investment accounts and balances for the given account id.

    Args:
        account_id: The customer's account id'
    """
    # update the context
    context.context.account_id = account_id
    return investment_acct_mgr.list_investment_accounts(account_id)

@function_tool
async def close_investment(context: RunContextWrapper[AccountContext], account_id: str, investment_id: str):
    context.context.account_id = account_id
    # Note a real close investment would be much more complex and would not delete the actual account
    investment_acct_mgr.delete_investment_account(account_id, investment_id)

# @function_tool
# async def login(username: str, password: str) -> dict:
#     if "foo" == username and "bar" == password:
#         return {
#             "account_id": "123"
#         }
#     else:
#         return {
#             "error": "invalid credentials"
#         }

### Agents

beneficiary_agent = Agent[AccountContext](
    name=BENE_AGENT_NAME,
    handoff_description=BENE_HANDOFF,
    instructions=BENE_INSTRUCTIONS,
    tools=[list_beneficiaries, add_beneficiaries, delete_beneficiaries],
)

investment_agent = Agent[AccountContext](
    name=INVEST_AGENT_NAME,
    handoff_description=INVEST_HANDOFF,
    instructions=INVEST_INSTRUCTIONS,
    tools=[list_investments, open_investment, close_investment],
)

supervisor_agent = Agent[AccountContext](
    name=SUPERVISOR_AGENT_NAME,
    handoff_description=SUPERVISOR_HANDOFF,
    instructions=SUPERVISOR_INSTRUCTIONS,
    # tools=[login],
    handoffs=[
        beneficiary_agent,
        investment_agent,
    ]
)

beneficiary_agent.handoffs.append(supervisor_agent)
investment_agent.handoffs.append(supervisor_agent)

async def run(mcp_server: MCPServer):
    # Set up the user_account agent to know about the MCP Server
    supervisor_agent.mcp_servers=[mcp_server]

    current_agent: Agent[AccountContext] = supervisor_agent
    input_items: list[TResponseInputItem] = []
    context = AccountContext()

    conversation_id = uuid.uuid4().hex[:16]

    print("Welcome to ABC Wealth Management. How can I help you?")
    while True:
        user_input = input("Enter your message: ")
        lower_input = user_input.lower() if user_input is not None else ""
        if lower_input == "exit" or lower_input == "end" or lower_input == "quit":
            break
        # with trace("wealth management", group_id=conversation_id):
        input_items.append({"content": user_input, "role": "user"})
        result = await Runner.run(current_agent, input_items, context=context)

        for new_item in result.new_items:
            agent_name = new_item.agent.name
            if isinstance(new_item, MessageOutputItem):
                print(f"{agent_name} {ItemHelpers.text_message_output(new_item)}")
            elif isinstance(new_item, HandoffOutputItem):
                print(f"Handed off from {new_item.source_agent.name} to {new_item.target_agent.name}")
            elif isinstance(new_item, ToolCallItem):
                print(f"{agent_name}: Calling a tool")
            elif isinstance(new_item, ToolCallOutputItem):
                print(f"{agent_name}: Tool call type: {new_item.type} output: {new_item.output}")

            else:
                print(f"{agent_name}: Skipping item: {new_item.__class__.__name__}")
        input_items = result.to_input_list()
        # print(f"****> Input items is {input_items}")
        current_agent = result.last_agent

### MCP Server

async def main():
    script_dir = os.path.dirname(__file__)
    # print(f"script_dir: {script_dir}")
    relative_path = '../mcpserver/runmcp.sh'
    mcp_script = os.path.join(script_dir, relative_path)
    # print(f"mcp_script: {mcp_script}")
    async with MCPServerStdio(
        name="Wealth Management MCP Server",
        params={
            "command": mcp_script
        },
    ) as server:
        trace_id = gen_trace_id()
        with trace(workflow_name="MCP Wealth Management Example", trace_id=trace_id):
            print(f"View trace: https://platform.openai.com/traces/trace?trace_id={trace_id}\n")
        await run(server)

if __name__ == "__main__":
    asyncio.run(main())