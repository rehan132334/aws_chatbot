from langchain_core.tools import tool
 
import os
from state import RAGConfig
from dotenv import load_dotenv
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
 
# Short, hand-written replacements for AWS's verbose tool descriptions.
# AWS's originals run 1,200-3,000+ chars each; these are ~50-90 chars.
# This is the single biggest lever on request size -- keep it in sync
# if the upstream MCP servers add/rename tools.
CONCISE_DESCRIPTIONS = {
    # aws-docs tools
    "read_documentation": "Fetch an AWS docs page and convert it to markdown.",
    "read_sections": "Fetch specific sections of an AWS docs page.",
    "search_table": "Search rows in a large AWS docs table (e.g. pricing/quotas).",
    "search_documentation": "Search AWS documentation by keyword.",
    "recommend": "Get related AWS docs page recommendations.",
    # aws-iac tools
    "validate_cloudformation_template": "Validate a CloudFormation template before deploy.",
    "check_cloudformation_template_compliance": "Check a CFN template against AWS best practices.",
    "troubleshoot_cloudformation_deployment": "Diagnose a failed CloudFormation deployment.",
    "get_cloudformation_pre_deploy_validation_instructions": "Get pre-deploy validation steps for CFN.",
    "search_cdk_documentation": "Search AWS CDK documentation.",
    "search_cloudformation_documentation": "Search CloudFormation resource/property docs.",
    "search_cdk_samples_and_constructs": "Find CDK code samples and constructs.",
    "cdk_best_practices": "Get CDK best practices guidance.",
    "read_iac_documentation_page": "Fetch an IaC (CDK/CFN) documentation page.",
}
 
# Which tool names belong to which category, so we can bind only the
# subset relevant to a given query instead of all of them at once.
DOCS_TOOL_NAMES = {
    "read_documentation",
    "read_sections",
    "search_table",
    "search_documentation",
    "recommend",
}
IAC_TOOL_NAMES = {
    "validate_cloudformation_template",
    "check_cloudformation_template_compliance",
    "troubleshoot_cloudformation_deployment",
    "get_cloudformation_pre_deploy_validation_instructions",
    "search_cdk_documentation",
    "search_cloudformation_documentation",
    "search_cdk_samples_and_constructs",
    "cdk_best_practices",
    "read_iac_documentation_page",
}
 
 
async def get_mcp_tools():
    """Connects to MCP servers and exposes tools to LangChain/LangGraph."""
    client = MultiServerMCPClient(
        {
            "aws-docs": {
                "command": "uvx",
                "args": ["awslabs.aws-documentation-mcp-server@latest"],
                "env": {
                    "FASTMCP_LOG_LEVEL": "ERROR",
                    "AWS_DOCUMENTATION_PARTITION": "aws",
                },
                "transport": "stdio",
            },
            "aws-iac": {
                "command": "uvx",
                "args": ["awslabs.aws-iac-mcp-server@latest"],
                "transport": "stdio",
            },
        }
    )
    return await client.get_tools()
 
 
def _trim_descriptions(tools):
    """Overwrite each tool's verbose upstream description with a short one."""
    for t in tools:
        if t.name in CONCISE_DESCRIPTIONS:
            t.description = CONCISE_DESCRIPTIONS[t.name]
    return tools
 
 
def load_mcp_tools():
    """
    Sync helper for agent initialization.
    Returns (docs_tools, iac_tools) -- two separate lists so the caller
    can bind only the relevant subset per query instead of all tools
    at once.
    """
    all_tools = asyncio.run(get_mcp_tools())
    all_tools = _trim_descriptions(all_tools)
 
    docs_tools = [t for t in all_tools if t.name in DOCS_TOOL_NAMES]
    iac_tools = [t for t in all_tools if t.name in IAC_TOOL_NAMES]
 
    unmatched = [t.name for t in all_tools if t.name not in DOCS_TOOL_NAMES and t.name not in IAC_TOOL_NAMES]
    if unmatched:
        print(f"[tools.py] Warning: unclassified tools loaded, not bound anywhere: {unmatched}")
 
    return docs_tools, iac_tools
 