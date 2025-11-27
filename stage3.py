import os
import json
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
# make a supabase client if needed
from supabase import create_client, Client



load_dotenv()


supabase_url = os.getenv("SUPABASE_URL")
# Use anon key for all operations (RLS rules must permit writes)
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# ----- Schemas -----
class GeminiScoreResponse(BaseModel):
    SCORE: int = Field(..., description="Lead score between 0 and 100")
    RESPONSE: str = Field(..., description="Reasoning for the score. Write within the range of 50-100 words.")
    SHOULD_CONTACT: int = Field(..., description="1 if lead should be contacted, else 0")

class GeminiMessageResponse(BaseModel):
    SUBJECT: str = Field(..., description="A catchy subject line for the outreach email, within 5-7 words.")
    MESSAGE: str = Field(..., description="A personalized outreach message for the lead, within 50-70 words.")

class GeminiPostAnalysisResponse(BaseModel):
    POST_ANALYSIS: str = Field(
        ..., description="Exactly two lines. Line 1: concise summary of the post's core message (no hashtags/links). Line 2: actionable insight/opportunity relevant to WildnetEdge services (no hashtags/links). Use a single newline between lines."
    )

# Load company context
# with open("stages/wildnetEdge.txt", "r") as f:
#     wildnet_edge_data = f.read()

# ----- Core function -----
def process_lead(lead_info: dict, api_key: str, wildnet_data, scoring_criteria_and_ICP, message_prompt, post_analysis_prompt: Optional[str] = None) -> dict:
    """
    1. Score lead (GeminiScoreResponse) using existing scoring prompt (unchanged).
    2. If score >= 50 generate SUBJECT + MESSAGE (GeminiMessageResponse).
       Else set both to 'ineligible'.
    3. Return required fields.
    """
    # -------- Scoring Phase (prompt kept exactly as in stage3.py) --------
    scoring_llm = ChatGoogleGenerativeAI(
        model='models/gemini-2.5-flash',
        google_api_key=api_key,
        temperature=0.3
    )
    score_parser = PydanticOutputParser(pydantic_object=GeminiScoreResponse)
    score_format = score_parser.get_format_instructions()

    scoring_system_msg = SystemMessage(content=f"""
You are an expert lead qualifier. We (WildnetEdge) as a company offer the following services to our clients:
WildnetEdge: ```{wildnet_data}```

Scoring criteria and ICP:
```{scoring_criteria_and_ICP}```
""")

    scoring_human_msg = HumanMessage(content=f"""
Evaluate this lead for potential:
Lead Info: ```{lead_info}```

Should we approach this lead? Score the leads based on above rule (0-100) and explain your reasoning and lead's location based on how well they match our services. Keep the score criteria strict and give high score only to those who fulfill all the criteria to a good extent.

Score format: ```{score_format}```
""")

    score_raw = scoring_llm.invoke([scoring_system_msg, scoring_human_msg])
    score_parsed = score_parser.parse(score_raw.content)

    final_score = score_parsed.SCORE
    should_contact = score_parsed.SHOULD_CONTACT
    reasoning = score_parsed.RESPONSE

    # -------- Message Phase (only if score >= 50) --------
    if final_score >= 50:
        msg_llm = ChatGoogleGenerativeAI(
            model='models/gemini-2.5-flash',
            google_api_key=api_key,
            temperature=0.6
        )
        msg_parser = PydanticOutputParser(pydantic_object=GeminiMessageResponse)
        msg_format = msg_parser.get_format_instructions()

        # Using same wildnet_edge_data context; (original message.py prompt body not provided, keep minimal)
        message_system = SystemMessage(content=f"""
You are an expert SDR crafting concise personalized outreach.
Company context (WildnetEdge services):
```{wildnet_data}```

Message prompt:
```{message_prompt}```
""")

        message_human = HumanMessage(content=f"""
Lead info:
{lead_info}

Generate outreach.
{msg_format}
""")

        msg_raw = msg_llm.invoke([message_system, message_human])
        msg_parsed = msg_parser.parse(msg_raw.content)
        subject = msg_parsed.SUBJECT
        message = msg_parsed.MESSAGE
    else:
        subject = "ineligible"
        message = "ineligible"

    # -------- Post Analysis (always generate) --------
    post_content = lead_info.get("post_content")

    if not post_content:
        # Try fetching from DB as fallback
        try:
            lead_id = lead_info.get("lead_id")
            if lead_id:
                resp_pc = supabase.table("all_leads").select("post_content").eq("lead_id", lead_id).limit(1).execute()
                rows_pc = (resp_pc.data or [])
                if rows_pc:
                    post_content = rows_pc[0].get("post_content")
        except Exception:
            post_content = None

    if post_content and isinstance(post_content, str) and post_content.strip():
        analysis_llm = ChatGoogleGenerativeAI(
            model='models/gemini-2.5-flash',
            google_api_key=api_key,
            temperature=0.4
        )
        analysis_parser = PydanticOutputParser(pydantic_object=GeminiPostAnalysisResponse)
        analysis_format = analysis_parser.get_format_instructions()

        # Use provided prompt if present, otherwise a minimal default that enforces two lines
        default_prompt = (
            "Produce exactly two lines. Line 1: Concise neutral summary of the post's main message (no hashtags or links). "
            "Line 2: Actionable insight/opportunity relevant to WildnetEdge's services (no hashtags or links)."
        )
        effective_prompt = (post_analysis_prompt or "").strip() or default_prompt

        analysis_system = SystemMessage(content=f"""
    You are an expert SDR analyst.
    Company context (WildnetEdge services):
    ```{wildnet_data}```
    """)

        analysis_human = HumanMessage(content=f"""
    Given this social post content (may include hashtags/links):
    ```{post_content}```

    Instructions for analysis:
    {effective_prompt}

    Output format:
    {analysis_format}
    """)

        analysis_raw = analysis_llm.invoke([analysis_system, analysis_human])
        analysis_parsed = analysis_parser.parse(analysis_raw.content)
        post_analysis = analysis_parsed.POST_ANALYSIS
        # Enforce exactly two lines after generation (sanitization layer)
        if post_analysis:
            txt = post_analysis.strip().replace('\r\n', '\n')
            lines = [l.strip() for l in txt.split('\n') if l.strip()]
            # Fallback to sentence split if fewer than 2 lines
            if len(lines) < 2:
                sentences = [s.strip() for s in txt.replace('\n', ' ').split('.') if s.strip()]
                for s in sentences:
                    if len(lines) >= 2:
                        break
                    if s not in lines:
                        lines.append(s)
            # Trim to first two
            if len(lines) > 2:
                lines = lines[:2]
            # Hard length cap per line (optional)
            lines = [l[:400] for l in lines]
            if len(lines) == 2:
                post_analysis = '\n'.join(lines)
            elif len(lines) == 1:
                post_analysis = f"{lines[0]}\n(No further insight)"
            else:
                post_analysis = "No analysis\nNo insight"
    else:
        post_analysis = "No post content available.\nNo actionable insight due to missing post content."

    result = {
        "lead_id": lead_info.get("lead_id"),
        "name": lead_info.get("name"),
        "linkedin_url": lead_info.get("profile_url") or lead_info.get("linkedin_url"),
        "location": lead_info.get("location"),
        "score": final_score,
        "response": reasoning,
        "should_contact": should_contact,
        "message": message,
        "subject": subject,
        "post_analysis": post_analysis,
    }

    # Persist result and update lead flag in Supabase (mirroring batch behavior)
    if result:
        # Upsert to avoid duplicate key violations if reprocessed
        try:
            supabase.table("llm_response").upsert(result, on_conflict="lead_id").execute()
        except Exception as e:
            # Fallback to insert if upsert not available in client version
            try:
                supabase.table("llm_response").insert(result).execute()
            except Exception as e2:
                print(f"Error inserting lead {lead_info.get('lead_id')}: {e2}")

        # Use the correct column name 'sent_to_llm'
        try:
            supabase.table("lead_details").update({"sent_to_llm": True}).eq("lead_id", lead_info.get("lead_id")).execute()
        except Exception as e:
            print(f"Error updating lead {lead_info.get('lead_id')}: {e}")
    else:
        print(f"Failed to process lead {lead_info.get('lead_id')}")

    return result

# # Optional batch helper
def process_leads(leads, api_key: str, wildnet_data, scoring_criteria_and_ICP, message_prompt, post_analysis_prompt: Optional[str] = None):
    llm_responses = []
    for ld in leads:
        print(f"Processing lead {ld.get('lead_id')} - {ld.get('name')}")
        result = process_lead(ld, api_key, wildnet_data, scoring_criteria_and_ICP, message_prompt, post_analysis_prompt)
        if result:
            llm_responses.append(result)
        else:
            print(f"Failed to process lead {ld.get('lead_id')}")
    return llm_responses

    # return [process_lead(ld, api_key) for ld in leads]

# if __name__ == "__main__":
#     # Simple manual test placeholder
#     api_key = os.getenv("GEMINI_API_KEY", "YOUR_KEY")
#     sample = {
#         "lead_id": "123",
#         "name": "Jane Doe",
#         "profile_url": "https://www.linkedin.com/in/example",
#         "location": "United States",
#         "title": "Director of Operations",
#         "company": "Acme Manufacturing",
#         "bio": "Operations leader focused on process optimization and enterprise systems transformation."
#     }
#     if api_key == "YOUR_KEY":
#         print("Set GEMINI_API_KEY in environment to run live test.")
#     else:
#         out = process_lead(sample, api_key)
#         print(json.dumps(out, indent=2))