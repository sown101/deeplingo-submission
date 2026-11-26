# DeepLingo v3 ERD

```mermaid
erDiagram
  profiles ||--o{ user_language_preferences : has
  languages ||--o{ user_language_preferences : configures
  languages ||--o{ romanization_systems : has
  languages ||--o{ videos : original_language
  languages ||--o{ video_transcripts : transcript_language
  channels ||--o{ videos : publishes
  videos ||--o{ video_transcripts : has
  video_transcripts ||--o{ transcript_segments : contains
  transcript_segments ||--o{ segment_translations : translated_as
  transcript_segments ||--o{ segment_romanizations : romanized_as
  romanization_systems ||--o{ segment_romanizations : renders
  languages ||--o{ dictionary_entries : has
  languages ||--o{ concepts : has
  dictionary_entries ||--o{ concept_dictionary_links : supports
  concepts ||--o{ concept_dictionary_links : linked_to
  concepts ||--o{ learning_objects : appears_as
  videos ||--o{ learning_objects : contains
  transcript_segments ||--o{ learning_objects : evidences
  profiles ||--o{ review_states : schedules
  concepts ||--o{ review_states : reviewed_as
  review_states ||--o{ review_events : records
  profiles ||--o{ saved_concepts : saves
  concepts ||--o{ saved_concepts : saved_as
  learning_objects ||--o{ saved_concepts : source_context
  profiles ||--o{ word_groups : owns
  word_groups ||--o{ word_group_items : contains
  saved_concepts ||--o{ word_group_items : grouped_as
```

## Core Flows

Content:

`channels -> videos -> video_transcripts -> transcript_segments -> learning_objects -> concepts`

Learning:

`review answer -> review_states + review_events + learner_activity_log`

Review:

`review_states -> review_events`

Collections:

`saved_concepts -> word_group_items -> word_groups`
