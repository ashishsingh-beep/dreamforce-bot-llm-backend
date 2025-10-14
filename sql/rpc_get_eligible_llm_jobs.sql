-- Creates an RPC function to fetch eligible leads joined with details and prompts
-- Conditions:
--   al.scrapped = true
--   al.lead_id = ld.lead_id
--   al.user_id = p.user_id and al.tag = p.tag
--   ld.sent_to_llm = false
-- Returns the columns required to build the single-lead payload and LLM context

create or replace function public.rpc_get_eligible_llm_jobs()
returns table (
  lead_id text,
  user_id uuid,
  tag text,
  name text,
  title text,
  location text,
  company_name text,
  experience text,
  skills text,
  bio text,
  profile_url text,
  linkedin_url text,
  company_page_url text,
  wildnet_data text,
  scoring_criteria_and_icp text,
  message_prompt text
)
language sql
stable
as $$
  select
    al.lead_id,
    al.user_id,
    al.tag,
    ld.name,
    ld.title,
    ld.location,
    ld.company_name,
    ld.experience,
    ld.skills,
    ld.bio,
  ld.profile_url,
  coalesce(al.linkedin_url, ld.profile_url) as linkedin_url,
    ld.company_page_url,
    p.wildnet_data,
    p.scoring_criteria_and_icp,
    p.message_prompt
  from public.all_leads al
  join public.lead_details ld on ld.lead_id = al.lead_id
  join (
      select distinct on (user_id, tag)
        user_id, tag, wildnet_data, scoring_criteria_and_icp, message_prompt, created_at
      from public.prompts
      order by user_id, tag, created_at desc
  ) p on p.user_id = al.user_id and p.tag = al.tag
  where al.scrapped = true
    and coalesce(ld.sent_to_llm, false) = false;
$$;

-- Optional: permissions (server uses service key; still safe to expose execute)
-- grant execute on function public.rpc_get_eligible_llm_jobs() to anon, authenticated;
