import json

from code_harness.core.llm_client import LLMClient


class MessageSummarizer:
    summary_prompt = """
            
        You are a Memory Compaction Agent.

Your task is to update an existing summary using newly compacted messages.

Inputs:

1. Existing Summary

   * May be empty.
   * Represents all previously compacted conversation history.

2. New Messages

   * Messages that are about to be removed from active context.

Your goal is to merge both sources into a single updated summary that preserves important information while minimizing token usage.

Rules:

1. Treat the Existing Summary as the source of truth for previously compacted history.

2. Incorporate any new information from New Messages into the Existing Summary.

3. Remove:

   * Duplicate information.
   * Repeated explanations.
   * Conversational filler.
   * Intermediate reasoning that does not affect future work.

4. Preserve:

   * Current goals.
   * User preferences.
   * Constraints.
   * Decisions made.
   * Completed work.
   * Pending work.
   * Important tool results.
   * Technical implementation details.
   * Open questions.
   * References to files, repositories, APIs, resources, and artifacts.

5. If New Messages contradict Existing Summary:

   * Prefer the most recent information.
   * Replace outdated facts.
   * Remove obsolete tasks that were completed.

6. The updated summary should be concise and self-contained.
   A future agent should be able to continue the work without needing the original compacted messages.

Output valid JSON only.

Schema:

{
"current_goal": "",
"completed_tasks": [],
"pending_tasks": [],
"important_decisions": [],
"constraints": [],
"technical_details": [],
"tool_results": [],
"files_and_resources": [],
"open_questions": []
}


                """

    @classmethod
    async def summarize_messages(
        cls, system_prompt, model, old_messages, existing_summary=None
    ) -> str:

        if existing_summary:
            content = json.dumps(
                {
                    "existing_summary": existing_summary,
                    "new_messages_to_merge": old_messages,
                },
                indent=2,
            )

        else:
            content = json.dumps(
                {
                    "new_messages_to_merge": old_messages,
                },
                indent=2,
            )

        llm_client = LLMClient()
        summarizer_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": content,
            },
        ]

        response = await llm_client.send(model, summarizer_messages)

        return response.choices[0].message.content

    @classmethod
    async def summarize_conversation_summary(
        cls,
        model,
        current_conversation_summary=None,
        user_summary=None,
        assistant_summary=None,
        tool_summary=None,
    ):

        content = f"""
                Summaries to merge:

                <current_conversation_summary>
                {current_conversation_summary or ""}
                </current_conversation_summary>

                <new_user_summary>
                {user_summary or ""}
                </new_user_summary>

                <new_assistant_summary>
                {assistant_summary or ""}
                </new_assistant_summary>

                <new_tool_interactions_summary>
                {tool_summary or ""}
                </new_tool_interactions_summary>
                """

        llm_client = LLMClient()
        summarizer_messages = [
            {
                "role": "system",
                "content": MessageSummarizer.conversation_summary_prompt,
            },
            {
                "role": "user",
                "content": content,
            },
        ]

        response = await llm_client.send(model, summarizer_messages)

        return response.choices[0].message.content
