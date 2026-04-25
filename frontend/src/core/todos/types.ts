import type { AIMessage } from "@langchain/langgraph-sdk";

export interface Todo {
  id?: string;
  content?: string;
  status?: "pending" | "in_progress" | "completed" | "failed";
  task_id?: string;
  task_prompt?: string;
  task_description?: string;
  subagent_type?: "general-purpose" | "bash" | string;
  latest_message?: AIMessage;
  stream_messages?: AIMessage[];
  result?: string;
  result_summary?: string;
  error?: string;
}
