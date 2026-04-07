# 10 — RAG Pipeline

This document explains exactly how a student's question becomes an answer, from the moment they click Send to the moment text appears in the chat.

---

## Pipeline Entry Points

There are two endpoints that trigger the pipeline:

| Endpoint | Mode | Returns |
|----------|------|---------|
| `POST /api/v1/chat/query` | Standard | Complete answer as JSON |
| `POST /api/v1/chat/query/stream` | Streaming | SSE token stream |

Both follow the same logic up to the final generation step.

---

## Step 1: Load Conversation Context

Before classifying intent, the pipeline loads:

1. **Recent messages** — last 10 messages (`SHORT_TERM_MEMORY_MESSAGES=10`) from the database, in chronological order. These will be passed to Gemini to give it short-term memory of the conversation.

2. **Conversation summary** — if the conversation has 20+ messages, a rolling summary may exist. It's checked and updated if needed (`SUMMARY_TRIGGER_MESSAGES=20`).

3. **Cache check** — the query + conversation_id are hashed. If an identical query was answered in the last hour, return the cached response immediately.

---

## Step 2: Intent Classification

Gemini Flash reads the user's query + the last 4 messages of history and returns a JSON:

```json
{
  "intent": "cross_reference",
  "is_safe": true,
  "subject_hint": "Machine Learning",
  "unit_hint": 3
}
```

**Intent meanings:**

| Intent | When to use | Example queries |
|--------|-------------|-----------------|
| `exam_question` | User wants to know what has appeared in exams | "What questions came from TCP/IP?" / "exam questions on OSI model" |
| `concept_explain` | User wants explanation/theory | "Explain what k-means clustering is" / "define TCP/IP" |
| `exam_prep` | User wants both questions AND explanations | "Help me prepare chapter 3" / "questions with answers on sorting" |
| `syllabus_unit` | User asks about chapter/unit topics | "What is covered in unit 2 of ML?" / "chapter 4 topics" |
| `cross_reference` | User wants exam questions from a specific chapter | "Unit 3 ML questions with explanations" / "chapter 2 data communication exam prep" |
| `chit_chat` | Greetings or off-topic | "Hi", "thanks", "what's your name" |

**`is_safe`** is `false` only for harmful or abusive content. If false, the pipeline returns a refusal message immediately without any retrieval.

**`subject_hint`** is extracted when the user names a subject: "Machine Learning" → matched against the syllabus table. `null` if no subject is mentioned.

**`unit_hint`** is the chapter/unit number as an integer, or `null` if not mentioned.

The intent classifier itself is a Gemini Flash call with `max_tokens=120`, so it's fast (~0.3–0.8 seconds).

---

## Step 3: Query Rewriting (optional)

If the conversation has more than 2 messages, the query might be a follow-up that only makes sense in context:

> User: "Tell me about unit 3 of Machine Learning"
> Assistant: "Unit 3 covers unsupervised algorithms..."
> User: "What exam questions are from it?"

The phrase "from it" refers to "unit 3 of Machine Learning". Gemini Flash rewrites this to:
> "What exam questions come from unit 3 of Machine Learning?"

This rewritten query is used for retrieval so the vector search is self-contained.

---

## Step 4: Syllabus Topic Lookup (for `syllabus_unit` and `cross_reference`)

When the intent is `syllabus_unit` or `cross_reference` (or when a `subject_hint` is present), the pipeline queries the `syllabus` table:

```sql
SELECT id, subject_code, subject_name, semester, year, units
FROM syllabus
WHERE similarity(subject_name, :hint) > 0.15
ORDER BY similarity(subject_name, :hint) DESC
LIMIT 1;
```

`similarity()` is provided by the `pg_trgm` extension. A threshold of 0.15 is quite permissive — it catches partial matches and abbreviations.

If a `unit_hint` was extracted (e.g., `3`), only that unit is returned:
```python
matched_units = [u for u in units if u.get("unit_no") == unit_hint]
```

Otherwise, all units are returned.

The result looks like:
```python
{
    "subject_name": "Machine Learning",
    "subject_code": "6CAI4-02",
    "semester": 6,
    "matched_units": [
        {
            "unit_no": 3,
            "unit_title": "Unsupervised learning algorithm",
            "topics": ["k-means clustering", "Hierarchical Clustering", "Apriori Algorithm"],
            "hours": 8
        }
    ]
}
```

This becomes the `syllabus_context` passed to the answer generator.

---

## Step 5: Query Enrichment

For `syllabus_unit` / `cross_reference`, the search query is enriched with topics from the syllabus:

```python
enriched_q = "Machine Learning: k-means clustering, Hierarchical Clustering, Apriori Algorithm, ..."
```

This enriched query is embedded and used for vector search. By including topic keywords that appear in actual lecture notes and exam papers, retrieval precision improves significantly.

For other intents, the original (possibly rewritten) query is used directly.

---

## Step 6: Vector Retrieval

The enriched query is embedded using `gemini-embedding-001` with `task_type="RETRIEVAL_QUERY"`.

Then, depending on intent:

| Intent | Searches |
|--------|---------|
| `exam_question` | `document_chunks` only |
| `concept_explain` | `notes` only |
| `exam_prep` | `document_chunks` + `notes` |
| `syllabus_unit` | `notes` only (using enriched query) |
| `cross_reference` | `document_chunks` + `notes` (using enriched query) |

**Search query:**
```sql
SELECT id, chunk_text, ...,
       1 - (embedding <=> CAST(:vec AS vector)) AS score
FROM document_chunks
WHERE embedding IS NOT NULL
  AND (embedding <=> CAST(:vec AS vector)) < :threshold  -- distance threshold
ORDER BY embedding <=> CAST(:vec AS vector)
LIMIT 8;
```

- `:threshold` = `1 - SIMILARITY_THRESHOLD` = `1 - 0.65` = `0.35` (cosine distance)
- Chunks with similarity < 0.65 (distance > 0.35) are excluded
- Top 8 results (`TOP_K_RETRIEVAL=8`) are returned

---

## Step 7: MMR De-duplication

Before combining exam and notes results, the system applies **Maximal Marginal Relevance (MMR)** — a text-level deduplication that removes near-duplicate chunks.

Two chunks are considered duplicates if over 80% of their words overlap. This prevents the same question from appearing multiple times if it was asked in different exams.

The implementation is a simplified MMR (no re-ranking with stored vectors — just deduplication):
```python
words = set(chunk_text.lower().split())
is_dup = any(
    len(words & set(seen.lower().split())) / max(len(words), 1) > 0.8
    for seen in seen_texts
)
```

---

## Step 8: Build Prompt Messages

The context block assembled for Gemini is a structured document:

```
[Syllabus: Machine Learning | Sem 6]
Unit 3: Unsupervised learning algorithm
Topics: k-means clustering, Hierarchical Clustering, Apriori Algorithm, ...

---

[Exam Q1 | Part B | Q3 | 10 marks] Machine Learning
[Subject: Machine Learning | Code: 6CAI4-02 | Part B | Q3 | 10 marks]
Explain the k-means clustering algorithm with an example.

---

[Notes p.42] Machine Learning
K-means clustering is an unsupervised machine learning algorithm...
The algorithm works by partitioning n observations into k clusters...

---

[Exam Q2 | Part A | Q1 | 5 marks] Machine Learning
Define unsupervised learning. Give two examples.
```

This is appended to the user's question:
```
Context:
[context block above]

---

Question: What are the topics in unit 3 of Machine Learning and what questions appeared in the exam?
```

The full message list sent to Gemini:
```python
[
    {"role": "system", "content": _RAG_SYSTEM},  # instructions
    # optional: {"role": "system", "content": summary}
    {"role": "user", "content": "previous question 1"},
    {"role": "assistant", "content": "previous answer 1"},
    # ... recent history ...
    {"role": "user", "content": "Context:\n...\nQuestion: ..."},  # current query
]
```

---

## Step 9: Final Generation

Gemini Pro (`gemini-2.5-pro`) generates the final answer with:
- `temperature=0.3` — mostly deterministic but allows natural language variation
- `max_tokens=2048` — maximum response length
- System prompt enforces: cite sources, use only provided context, don't invent facts

---

## Step 10: Save and Return

1. Save the assistant's message to the `messages` table (committed immediately)
2. Build `CitedChunk` objects from retrieved results
3. Cache the response in Redis
4. Return `ChatResponse`:
   ```json
   {
     "message_id": "uuid",
     "conversation_id": "uuid",
     "answer": "Unit 3 of Machine Learning covers...",
     "intent": "cross_reference",
     "sources": [
       {
         "chunk_id": "uuid",
         "source_type": "exam",
         "subject_name": "Machine Learning",
         "subject_code": "6CAI4-02",
         "excerpt": "[Subject: Machine Learning | Part B | Q3 | 10 marks]\nExplain k-means...",
         "relevance_score": 0.8234
       }
     ],
     "model_used": "gemini-2.5-pro",
     "latency_ms": 4821
   }
   ```

---

## Streaming Mode

For streaming (`/chat/query/stream`), the pipeline runs identically up through step 8. Instead of `agenerate_with_history()`, it calls `astream()`:

```python
async def astream(messages, model, system, ...) -> AsyncGenerator[str, None]:
    # Runs the sync SDK stream in a thread
    # Puts tokens into a Queue
    # Yields tokens via async generator
```

The tokens are wrapped in Server-Sent Events format:
```
data: {"token": "Unit"}
data: {"token": " 3"}
data: {"token": " of"}
...
data: {"done": true}
```

The frontend reads these chunks and appends them to the streaming message in real-time, creating the "typing" effect.

---

## The RAG System Prompt

The system prompt enforces grounding:

```
You are an intelligent university study assistant with access to three sources:
1. Exam Questions (past papers) — actual questions that appeared in exams
2. Lecture Notes — explanations, theory, and concepts  
3. Syllabus — chapter/unit structure and topic mapping

RULES:
1. Use ONLY the provided context. Do not use prior knowledge.
2. For exam questions, clearly show question number, marks, and part if available.
3. For explanations, be thorough but grounded in the notes provided.
4. For chapter/unit queries, reference the specific unit and topics from syllabus.
5. If context is insufficient, say: "I couldn't find enough information in the uploaded materials."
6. Cite sources using [Exam Q1], [Notes p.X], [Syllabus Unit N] format.
```

---

## Typical Latency Breakdown

For a `cross_reference` query:

| Step | Typical Time |
|------|-------------|
| Intent classification (Gemini Flash) | 400–800ms |
| Query rewriting (if needed) | 300–600ms |
| Syllabus lookup (SQL) | 10–50ms |
| Query embedding | 200–400ms |
| Vector search (document_chunks) | 20–100ms |
| Vector search (notes) | 20–100ms |
| Final generation (Gemini Pro) | 3,000–8,000ms |
| **Total** | **4–10 seconds** |

Streaming reduces perceived latency because the first token appears in ~1 second while the rest streams in.
