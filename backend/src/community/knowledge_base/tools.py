from langchain.tools import tool

from src.community.knowledge_base.retriever import get_retriever


@tool("knowledge_search", parse_docstring=True)
def knowledge_search_tool(query: str) -> str:
    """Search the internal knowledge base for domain-specific information.

    Use this tool when the user asks questions about specialized domain knowledge,
    internal company information, or topics covered in the knowledge base.
    
    This tool searches through curated internal documents and returns relevant
    knowledge snippets with source document references.

    Args:
        query: The search query describing what information you need.
    """
    try:
        retriever = get_retriever()
        results = retriever.search(query)
    except Exception as e:
        return f"Error searching knowledge base: {e}"

    if not results:
        return "No relevant information found in the knowledge base."

    formatted_output = "## 检索结果\n\n"
    
    for i, result in enumerate(results, 1):
        content = result["content"].strip()
        filename = result.get("filename", "Unknown")
        score = result.get("score", 0.0)
        
        # Format the output for the agent
        formatted_output += f"### 来源 {i}: {filename} - 相关度: {score:.2f}\n"
        formatted_output += f"{content}\n"
        formatted_output += f"文档链接: /api/knowledge/docs/{filename}\n\n"

    # Add instructions for citation
    formatted_output += "---\n"
    formatted_output += "IMPORTANT: When using information from these knowledge base results in your response,\n"
    formatted_output += "you MUST cite the source using this format: [citation:Document Title](/api/knowledge/docs/filename.md)\n"
    formatted_output += "Also include a \"参考文献\" / \"References\" section at the end of your response listing all cited documents."

    return formatted_output
