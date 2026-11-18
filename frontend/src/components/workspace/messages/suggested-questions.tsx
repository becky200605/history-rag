import { useQuery } from "@tanstack/react-query";

/** This request starts only after the agent stream has completed. */
export function SuggestedQuestions({
  threadId,
  messageId,
  question,
  answer,
  enabled,
}: {
  threadId: string;
  messageId: string;
  question: string;
  answer: string;
  enabled: boolean;
}) {
  const { data } = useQuery({
    queryKey: ["suggested-questions", threadId, messageId, question, answer],
    enabled: enabled && !!question && !!answer && !answer.includes("建议问题"),
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    retry: false,
    queryFn: async ({ signal }): Promise<string[]> => {
      const response = await fetch("/api/secure-suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question.slice(0, 4000),
          answer: answer.slice(0, 24000),
        }),
        signal,
      });
      if (!response.ok) return [];
      const result = (await response.json()) as { questions?: unknown };
      return Array.isArray(result.questions)
        ? result.questions
            .filter((item): item is string => typeof item === "string")
            .slice(0, 3)
        : [];
    },
  });
  if (!enabled || !data?.length) return null;
  return (
    <div className="my-3 text-sm">
      <p className="mb-2 font-medium">建议问题</p>
      <ol className="list-decimal space-y-1 pl-5">
        {data.map((question) => (
          <li key={question}>{question}</li>
        ))}
      </ol>
    </div>
  );
}
