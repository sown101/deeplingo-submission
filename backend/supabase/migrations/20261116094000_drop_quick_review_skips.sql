-- DRAFT. Not applied to any environment. Applying it needs the owner's approval for that environment. Run it only
-- after the backend without the skipped-words routes is deployed. Forward-only.
--
-- "Take this word out of review" belonged to the old Quick review engine. The function that wrote a skip
-- (skip_quick_review_item) is dropped by 20261116091000, so nothing can add a row any more; the Notebook list and
-- its restore button were removed with it (owner decision 2026-11-15). This migration removes the last readers:
-- the two deck functions of the review engine stop excluding skipped words (same signatures, same results while the
-- table is empty), then the table goes.

create or replace function v3.review_deck_counts(p_user_id uuid)
returns table(language_code text, due_count bigint, new_count bigint, total_count bigint)
language sql stable security invoker set search_path = '' as $$
  select c.language_code,
         count(*) filter (where r.id is not null and r.due_at <= now()),
         count(*) filter (where r.id is null),
         count(*)
    from v3.saved_concepts sc
    join v3.concepts c on c.id = sc.concept_id
    left join v3.review_states r
      on r.user_id = sc.user_id and r.concept_id = sc.concept_id and r.review_mode = 'concept_to_meaning'
   where sc.user_id = p_user_id and sc.status in ('active', 'backlog') and sc.explicit
     and not exists (select 1 from v3.learner_known_concepts k where k.user_id = sc.user_id and k.concept_id = sc.concept_id)
   group by c.language_code;
$$;

-- Due cards first (earliest due), then new cards (newest save first). With p_concept_ids, exactly those saved words.
create or replace function v3.review_deck_cards(p_user_id uuid, p_language_code text, p_limit integer,
                                                p_concept_ids uuid[] default null)
returns table(concept_id uuid, due_at timestamptz, is_new boolean)
language sql stable security invoker set search_path = '' as $$
  select sc.concept_id, r.due_at, r.id is null
    from v3.saved_concepts sc
    join v3.concepts c on c.id = sc.concept_id and c.language_code = p_language_code
    left join v3.review_states r
      on r.user_id = sc.user_id and r.concept_id = sc.concept_id and r.review_mode = 'concept_to_meaning'
   where sc.user_id = p_user_id and sc.status in ('active', 'backlog') and sc.explicit
     and not exists (select 1 from v3.learner_known_concepts k where k.user_id = sc.user_id and k.concept_id = sc.concept_id)
     and case when p_concept_ids is null then (r.id is null or r.due_at <= now())
              else sc.concept_id = any(p_concept_ids) end
   order by r.id is null, r.due_at, sc.created_at desc
   limit least(greatest(coalesce(p_limit, 20), 1), 200);
$$;

drop table if exists v3.learner_quick_review_skips;
