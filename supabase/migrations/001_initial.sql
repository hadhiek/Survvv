-- Run in the Supabase SQL editor. Supabase Auth owns auth.users; never store passwords here.
create type public.survey_status as enum ('DRAFT','ACTIVE','COMPLETED','CLOSED','CANCELLED');
create type public.session_status as enum ('STARTED','COMPLETED','EXPIRED');
create type public.transaction_type as enum ('RESERVATION','COMPLETION','REFUND','ADJUSTMENT');
create type public.transaction_status as enum ('LOCKED','PENDING','CONFIRMED','RETURNED');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique check (email like '%@nitc.ac.in'), roll_number text not null unique,
  gender text not null, program text not null, batch int not null, department text not null, year int not null check (year between 1 and 8), role text not null default 'STUDENT' check (role in ('STUDENT','ADMIN')),
  credits int not null default 0 check (credits >= 0), locked_credits int not null default 0 check (locked_credits >= 0),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.surveys (
  id bigint generated always as identity primary key, creator_id uuid not null references public.profiles(id), title text not null,
  description text not null, google_form_url text not null, form_id text not null, participation_field_entry text not null,
  webhook_secret_hash text not null, estimated_minutes int not null check (estimated_minutes > 0),
  reward_per_response int not null check (reward_per_response between 1 and 10), status public.survey_status not null default 'DRAFT', created_at timestamptz not null default now()
);
create table public.survey_requirements (
  id bigint generated always as identity primary key, survey_id bigint not null references public.surveys(id) on delete cascade,
  department text not null, year int not null, gender text not null, quota int not null check(quota > 0), filled int not null default 0 check(filled between 0 and quota),
  unique(survey_id,department,year,gender)
);
create table public.survey_sessions (
  id bigint generated always as identity primary key, survey_id bigint not null references public.surveys(id), user_id uuid not null references public.profiles(id),
  requirement_id bigint not null references public.survey_requirements(id), token text not null unique, status public.session_status not null default 'STARTED', started_at timestamptz not null default now(), unique(survey_id,user_id)
);
create table public.responses (
  id bigint generated always as identity primary key, survey_id bigint not null references public.surveys(id), user_id uuid not null references public.profiles(id), session_id bigint not null unique references public.survey_sessions(id), received_at timestamptz not null default now(), unique(survey_id,user_id)
);
create table public.credit_transactions (
  id bigint generated always as identity primary key, user_id uuid not null references public.profiles(id), survey_id bigint references public.surveys(id), amount int not null,
  type public.transaction_type not null, status public.transaction_status not null, idempotency_key text not null unique, created_at timestamptz not null default now()
);
create index survey_requirement_match_idx on public.survey_requirements(department,year,gender) where filled < quota;
create index survey_active_idx on public.surveys(status) where status='ACTIVE';

alter table public.profiles enable row level security;
alter table public.surveys enable row level security;
alter table public.survey_requirements enable row level security;
alter table public.survey_sessions enable row level security;
alter table public.responses enable row level security;
alter table public.credit_transactions enable row level security;
-- Browser access is read-only; FastAPI uses the service role and remains the write authority.
create policy "profile is visible to owner" on public.profiles for select using (auth.uid()=id);
create policy "users can read active surveys" on public.surveys for select using (status='ACTIVE' or creator_id=auth.uid());
create policy "users can read survey quotas" on public.survey_requirements for select using (true);

-- Create profiles from verified Auth registrations. App must still collect the remaining fields.
create or replace function public.handle_new_user() returns trigger language plpgsql security definer set search_path=public as $$
begin
  if new.email not like '%@nitc.ac.in' then raise exception 'Only @nitc.ac.in addresses are allowed'; end if;
  insert into public.profiles(id,email,roll_number,gender,program,batch,department,year)
  values(new.id,new.email,'pending-' || new.id,'Unspecified','Unspecified',2024,'Unspecified',1);
  return new;
end; $$;
create trigger on_auth_user_created after insert on auth.users for each row execute procedure public.handle_new_user();
