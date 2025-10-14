import os
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.output_parsers import PydanticOutputParser
# make a supabase client if needed
from supabase import create_client, Client



load_dotenv()


supabase_url = os.getenv("SUPABASE_URL")
# Prefer service role for server-side actions (RLS may be disabled but safe)
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# ----- Schemas -----
class GeminiScoreResponse(BaseModel):
    SCORE: int = Field(..., description="Lead score between 0 and 100")
    RESPONSE: str = Field(..., description="Reasoning for the score. Write within the range of 50-100 words.")
    SHOULD_CONTACT: int = Field(..., description="1 if lead should be contacted, else 0")

class GeminiMessageResponse(BaseModel):
    SUBJECT: str = Field(..., description="A catchy subject line for the outreach email, within 5-7 words.")
    MESSAGE: str = Field(..., description="A personalized outreach message for the lead, within 50-70 words.")

# Load company context
# with open("stages/wildnetEdge.txt", "r") as f:
#     wildnet_edge_data = f.read()

# ----- Core function -----
def process_lead(lead_info: dict, api_key: str, wildnet_data, scoring_criteria_and_ICP, message_prompt) -> dict:
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
def process_leads(leads, api_key: str, wildnet_data, scoring_criteria_and_ICP, message_prompt):
    llm_responses = []
    for ld in leads:
        print(f"Processing lead {ld.get('lead_id')} - {ld.get('name')}")
        result = process_lead(ld, api_key, wildnet_data, scoring_criteria_and_ICP, message_prompt)
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