-- Migration: add post_analysis column if missing.
alter table public.llm_response add column if not exists post_analysis text;
