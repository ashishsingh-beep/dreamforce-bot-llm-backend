-- New RPC function enabling initial processing and post-analysis backfill.
-- Selection rules:
--   A) lead_details.sent_to_llm = false (never processed)
--   B) OR existing llm_response row lacks post_analysis while a post_content now exists.
-- Relies on typo column post_analysis_promot in prompts, aliased as post_analysis_prompt.
create or replace function public.rpc_get_eligible_llm_jobs()
returns table (
  lead_id text,
  user_id uuid,
  tag text,
  name text,
  title text,
  location text,
  company_name text,
  experience jsonb,
  skills jsonb,
  bio text,
  profile_url text,
  linkedin_url text,
  company_page_url text,
  wildnet_data text,
  scoring_criteria_and_icp text,
  message_prompt text,
  post_analysis_prompt text,
  post_content text
)
language sql
stable
as $$
  select
    ld.lead_id,
    ld.user_id,
    ld.tag,
    ld.name,
    ld.title,
    ld.location,
    ld.company_name,
    ld.experience,
    ld.skills,
    ld.bio,
    ld.profile_url,
    coalesce(ld.linkedin_url, ld.profile_url) as linkedin_url,
    ld.company_page_url,
    p.wildnet_data,
    p.scoring_criteria_and_icp,
    p.message_prompt,
    p.post_analysis_promot as post_analysis_prompt,
    al.post_content
  from public.lead_details ld
  left join public.llm_response lr on lr.lead_id = ld.lead_id
  left join public.all_leads al on al.lead_id = ld.lead_id
  join (
      select distinct on (user_id, tag)
        user_id,
        tag,
        wildnet_data,
        scoring_criteria_and_icp,
        message_prompt,
        post_analysis_promot,
        created_at
      from public.prompts
      order by user_id, tag, created_at desc
  ) p on p.user_id = ld.user_id and p.tag = ld.tag
  where (
    coalesce(ld.sent_to_llm, false) = false
    OR (
      lr.lead_id is not null
      AND lr.post_analysis is null
      AND al.post_content is not null
    )
  );
$$;

create function public.rpc_get_eligible_llm_jobs()
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
  message_prompt text,
  post_analysis_prompt text, -- will be sourced from the typo
  post_content text
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
    p.message_prompt,
    /* alias the typo column */
    p.post_analysis_promot as post_analysis_prompt,
    al.post_content
  from public.lead_details ld
  join public.all_leads al on al.lead_id = ld.lead_id
  join (
      select distinct on (user_id, tag)
        user_id,
        tag,
        wildnet_data,
        scoring_criteria_and_icp,
        message_prompt,
        post_analysis_promot,
        created_at
      from public.prompts
      order by user_id, tag, created_at desc
  ) p on p.user_id = al.user_id and p.tag = al.tag
  where coalesce(ld.sent_to_llm, false) = false;
$$;