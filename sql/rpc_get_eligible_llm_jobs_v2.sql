-- v2: Drive from lead_details so new rows (sent_to_llm=false) are always considered
-- Joins all_leads (for user_id, tag) and prompts (latest per user_id+tag)
-- Note: Does NOT require al.scrapped=true to avoid missing new arrivals

create or replace function public.rpc_get_eligible_llm_jobs_v2()
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
    ld.lead_id,
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
  from public.lead_details ld
  join public.all_leads al on al.lead_id = ld.lead_id
  join (
      select distinct on (user_id, tag)
        user_id, tag, wildnet_data, scoring_criteria_and_icp, message_prompt, created_at
      from public.prompts
      order by user_id, tag, created_at desc
  ) p on p.user_id = al.user_id and p.tag = al.tag
  where coalesce(ld.sent_to_llm, false) = false;
$$;
