export interface Todo {
  id?: string;
  content?: string;
  status?: "pending" | "in_progress" | "completed" | "failed";
  task_id?: string;
  task_prompt?: string;
  subagent_type?: "general-purpose" | "bash" | string;
  result_summary?: string;
  error?: string;
}
