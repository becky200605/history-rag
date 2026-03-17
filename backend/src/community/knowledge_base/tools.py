from urllib.parse import quote

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
        source_type = result.get("source_type", "unknown")
        page = result.get("page")
        
        # Format the output for the agent
        if source_type == "pdf" and page is not None:
            # PyMuPDFLoader uses 0-based page, display as 1-based for users
            display_page = page + 1
            formatted_output += f"### 来源 {i}: {filename} (第{display_page}页) - 相关度: {score:.2f}\n"
            formatted_output += f"{content}\n"
            formatted_output += f"文档链接: /api/knowledge/docs/{quote(filename)}?page={page}\n\n"
        else:
            formatted_output += f"### 来源 {i}: {filename} - 相关度: {score:.2f}\n"
            formatted_output += f"{content}\n"
            formatted_output += f"文档链接: /api/knowledge/docs/{quote(filename)}\n\n"

    # Add instructions for citation with page support
    formatted_output += "---\n"
    formatted_output += "IMPORTANT: When using information from these knowledge base results in your response,\n"
    formatted_output += "you MUST cite the source using this format:\n\n"
    formatted_output += "For PDF documents with page numbers:\n"
    formatted_output += (
        "[citation:一小段你实际引用的原文](/api/knowledge/docs/filename.pdf"
        "?page=页码&snippet=和上面一致的那句原文，尽量简短，不要改动字句)\n\n"
    )
    formatted_output += "For markdown/text documents:\n"
    formatted_output += (
        "[citation:一小段你实际引用的原文](/api/knowledge/docs/filename.md"
        "?snippet=和上面一致的那句原文，尽量简短，不要改动字句)\n\n"
    )
    formatted_output += (
        "The `snippet` query parameter MUST be a short, verbatim excerpt from the original document that you used.\n"
    )
    formatted_output += (
        "The `page` parameter is the 0-based page index from the search results (use the exact number shown above).\n"
    )
    formatted_output += (
        "Also include a \"参考文献\" / \"References\" section at the end of your response listing all cited documents.\n"
    )
    formatted_output += (
        "Do NOT call web_search for this topic when the above results are sufficient."
    )

    return formatted_output
