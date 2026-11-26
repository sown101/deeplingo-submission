# Bao phủ giáo trình ngữ pháp transcript

Báo cáo đối chiếu các file `content/curriculum/<ngôn ngữ>/<cấp>.toml` với khung bao phủ (PRD FR-8.2, Q16, 2026-11-07): CEFR-J Grammar Profile 20180315, **chỉ cột CEFR-J** (`CEFR-J Level`, nếu trống thì `FREQ*DISP`; không dùng EGP, Core Inventory hay GSELO), và GF 0025-2021 (số mục, cấp; bản trích ivankra/hsk30). Nhãn mục chỉ ghi ngắn để người duyệt biết mục nào; lời giải và ví dụ trong giáo trình do DeepLingo viết.

Trạng thái: các file A2–C2 và HSK2–HSK6 là **bản nháp chờ chủ dự án duyệt mẫu**, chưa nạp vào DB. A1 và HSK1 là bản nháp cũ (2026-10-15); A1 được bổ sung 5 điểm ngày 2026-11-07.

Cách đọc:
- **trực tiếp**: một điểm ngữ pháp ghi `source_ref` là mục này;
- **gộp**: mục là dạng phủ định/nghi vấn hoặc biến thể của một mục đã có điểm, được giải thích trong điểm đó;
- **ở cấp khác**: mục có điểm ở file của cấp khác (ghi cấp);
- **ngoài phạm vi**: mục mô tả phân tích thành phần câu, không phải mẫu bôi chọn được trên transcript;
- **thiếu**: chưa có điểm nào.

## Tiếng Anh (CEFR-J)

| Cấp | Điểm trong file | Mục danh mục ở cấp này | Trực tiếp | Gộp | Ở cấp khác | Ngoài phạm vi | Thiếu |
|---|---|---|---|---|---|---|---|
| A1 | 24 | 81 | 24 | 26 | 1 | 4 | 26 |
| A2 | 36 | 43 | 33 | 8 | 0 | 1 | 1 |
| B1 | 33 | 52 | 31 | 19 | 0 | 1 | 1 |
| B2 | 42 | 70 | 42 | 19 | 0 | 0 | 9 |
| C1 | 26 | 0 | 0 | 0 | 0 | 0 | 0 |
| C2 | 16 | 0 | 0 | 0 | 0 | 0 | 0 |

CEFR-J không xếp mục nào ở C1/C2; 254 mục không có cấp CEFR-J. C1 và C2 dùng các mục không cấp này (ghi `source_ref`, trình nạp sẽ cảnh báo "has no level") và các điểm `deeplingo`; việc xếp chúng vào C1 hay C2 là đánh giá của DeepLingo, cần chủ dự án duyệt.

### A1

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 1 | I am [AFF. DEC.] | gộp → A1 `en.be_present` |
| 1-1 | I am not [NEG. DEC.] | gộp → A1 `en.be_present` |
| 2-2 | Are you ...? [AFF. INT.] | gộp → A1 `en.be_questions` |
| 3 | he/she is [AFF. DEC.] | gộp → A1 `en.be_present` |
| 3-1 | he/she is not [NEG. DEC.] | gộp → A1 `en.be_present` |
| 3-2 | Is he/she ...? [AFF. INT.] | gộp → A1 `en.be_questions` |
| 4 | we are [AFF. DEC.] | gộp → A1 `en.be_present` |
| 4-1 | we are not [NEG. DEC.] | gộp → A1 `en.be_present` |
| 5 | they are [AFF. DEC.] | gộp → A1 `en.be_present` |
| 5-1 | they are not [NEG. DEC.] | gộp → A1 `en.be_present` |
| 5-2 | Are they ...? [AFF. INT.] | gộp → A1 `en.be_questions` |
| 8-2 | Is this/that ...? [AFF. INT.] | gộp → A1 `en.this_that` |
| 10 | It is [AFF. DEC.] | thiếu |
| 14 | DEFINITE ARTICLES | thiếu |
| 15 | DETERMINERS: some/any | thiếu |
| 16 | DETERMINER: no | thiếu |
| 24 | INDEFINITE PRONOUNS | thiếu |
| 33 | ADVERBS: INTENSIFIERS: extremely/greatly/really/so/terribly/too/unbelievably/very | thiếu |
| 35 | ADVERBS OF NEGATION: never | thiếu |
| 55 | PHRASAL VERBS (V+PARTICLE) | thiếu |
| 57 | PHRASAL VERBS (V+PARTICLE+PREP+NP) | thiếu |
| 58-1 | TENSE/ASPECT: PRESENT (BE) [NEG. DEC.] | gộp → A1 `en.be_present` |
| 59-1 | TENSE/ASPECT: PRESENT (lexical verbs) [NEG. DEC.] | gộp → A1 `en.do_questions` |
| 60-2 | TENSE/ASPECT: PRESENT (lexical verbs; third person & singular) [AFF. INT.] | gộp → A1 `en.present_simple_third_person` |
| 61-2 | TENSE/ASPECT: PRESENT PROGRESSIVE [AFF. INT.] | gộp → A1 `en.present_progressive` |
| 64 | TENSE/ASPECT: PAST (BE) [AFF. DEC.] | gộp → A2 `en.a2.was_were` |
| 64-2 | TENSE/ASPECT: PAST (BE) [AFF. INT.] | gộp → A2 `en.a2.was_were` |
| 65 | TENSE/ASPECT: PRESENT (lexical verbs) [AFF. DEC.] | ở cấp khác → A2 `en.a2.past_simple` |
| 73 | PASSIVE: PRESENT [AFF. DEC.] | thiếu |
| 88 | TO-INFINITIVE: to DO (not preceded by 'not') | thiếu |
| 101 | VERB to DO | thiếu |
| 103 | VERB OBJECT to DO | thiếu |
| 105 | V-ING (not preceded by 'not') | thiếu |
| 110 | PREP+V-ING | thiếu |
| 117 | IMPERATIVE: AFFIRMATIVE (lexical verbs) [AFF. IMP.] | thiếu |
| 119 | Please+INFINITIVE [AFF. IMP.] | thiếu |
| 123-2 | MODAL/AUX: can [AFF. INT.] | gộp → A1 `en.can_ability` |
| 146-1 | there+be [NEG. DEC.] | gộp → A1 `en.there_is_are` |
| 146-2 | there+be [AFF. INT.] | gộp → A1 `en.there_is_are` |
| 150 | COORDINATING CONJUNCTIONS | thiếu |
| 155 | ADVERBIAL CLAUSE: when | thiếu |
| 161 | SUBORDINATE CLAUSE: after/albeit/although/because/before/despite/except/for/lest/like/once/since/so/than/though/till/unless/until/where/whereas/wheresoever/whether/while/whilst tagged as IN | thiếu |
| 162 | hope/know/think+CLAUSE (without 'that') | thiếu |
| 169 | POSTMODIFYING PRESENT | thiếu |
| 170 | PREMODIFYING PAST PARTICIPLE | thiếu |
| 171 | POSTMODIFYING PAST PARTICIPLE | thiếu |
| 172 | NOMINATIVE RELATIVE PRONOUN: who | gộp → B2 `en.b2.relative_subject` |
| 174 | NOMINATIVE RELATIVE PRONOUN: | gộp → B2 `en.b2.relative_subject` |
| 179 | ELLIPTICAL ACCUSATIVE RELATIVE PRONOUN | thiếu |
| 189 | PREPOSITION STRANDING | thiếu |
| 194-1 | SENTENCE PATTERN: SUBJECT+V [NEG. DEC.] | ngoài phạm vi |
| 194-2 | SENTENCE PATTERN: SUBJECT+V [AFF. INT.] | ngoài phạm vi |
| 196 | SENTENCE PATTERN: SUBJECT+V+OBJECT [AFF. DEC.] | ngoài phạm vi |
| 196-2 | SENTENCE PATTERN: SUBJECT+V+OBJECT [AFF. INT.] | ngoài phạm vi |
| 235 | WH- QUESTION: Why ...? [AFF. INT./NEG. INT.] | gộp → A1 `en.what_why_how` |
| 240 | WH- QUESTION: What N ...? [AFF. INT./NEG. INT.] | gộp → A1 `en.what_why_how` |
| 246 | WH- QUESTION: How ...? [AFF. INT./NEG. INT.] | gộp → A1 `en.what_why_how` |

### A2

Điểm dẫn mục của cấp khác hoặc mục không cấp: `en.a2.past_simple` ← 65 (A1); `en.a2.suggestions` ← 262 (không cấp); `en.a2.whose_question` ← 244 (không cấp).

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 62-2 | TENSE/ASPECT: PRESENT PERFECT [AFF. INT.] | gộp → A2 `en.a2.present_perfect` |
| 65-1 | TENSE/ASPECT: PRESENT (lexical verbs) [NEG. DEC.] | gộp → A2 `en.a2.past_did` |
| 69-2 | TENSE/ASPECT: FUTURE [AFF. INT.] | gộp → A2 `en.a2.will_future` |
| 132-3 | MODAL/AUX: might | gộp → A2 `en.a2.might` |
| 135-2 | MODAL/AUX: must | gộp → A2 `en.a2.must` |
| 135-3 | MODAL/AUX: must | gộp → A2 `en.a2.must` |
| 141 | MODAL/AUX: will [AFF. DEC.] | gộp → A2 `en.a2.will_future` |
| 168 | PREMODIFYING PRESENT PARTICIPLE | thiếu |
| 196-1 | SENTENCE PATTERN: SUBJECT+V+OBJECT [NEG. DEC.] | ngoài phạm vi |
| 252 | FUNCTIONAL QUESTION: Would you ...? [AFF. INT.] | gộp → A2 `en.a2.can_you_request` |

### B1

Điểm dẫn mục của cấp khác hoặc mục không cấp: `en.b1.exclamations` ← 192 (không cấp); `en.b1.make_object_adjective` ← 199 (không cấp).

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 2 | You are [AFF. DEC.] | gộp → A1 `en.be_present` |
| 12 | These/Those N [AFF. DEC./NEG. DEC.] | gộp → A2 `en.a2.this_that_noun` |
| 60-1 | TENSE/ASPECT: PRESENT (lexical verbs; third person & singular) [NEG. DEC.] | gộp → A1 `en.present_simple_third_person` |
| 61-1 | TENSE/ASPECT: PRESENT PROGRESSIVE [NEG. DEC.] | gộp → A1 `en.present_progressive` |
| 62-1 | TENSE/ASPECT: PRESENT PERFECT [NEG. DEC.] | gộp → A2 `en.a2.present_perfect` |
| 66-1 | TENSE/ASPECT: PAST PROGRESSIVE [NEG. DEC.] | gộp → A2 `en.a2.past_progressive` |
| 69-1 | TENSE/ASPECT: FUTURE [NEG. DEC.] | gộp → A2 `en.a2.will_future` |
| 76-1 | PASSIVE: PAST [NEG. DEC.] | gộp → A2 `en.a2.passive_past` |
| 117-1 | IMPERATIVE: AFFIRMATIVE (lexical verbs) [NEG. IMP] | thiếu |
| 124-1 | MODAL/AUX: could [NEG. DEC.] | gộp → B1 `en.b1.could` |
| 124-2 | MODAL/AUX: could [AFF. INT.] | gộp → B1 `en.b1.could` |
| 132 | MODAL/AUX: might [B1.1] | gộp → A2 `en.a2.might` |
| 136-1 | MODAL/AUX: need (to) | gộp → A2 `en.a2.need_to` |
| 136-2 | MODAL/AUX: need (to) | gộp → A2 `en.a2.need_to` |
| 136-3 | MODAL/AUX: need (to) | gộp → A2 `en.a2.need_to` |
| 139-1 | MODAL/AUX: should [NEG. DEC.] | gộp → A2 `en.a2.should` |
| 141-1 | MODAL/AUX: will [NEG. DEC.] | gộp → A2 `en.a2.will_future` |
| 142-2 | MODAL/AUX: would [AFF. INT.] | gộp → A2 `en.a2.would_like` |
| 153 | know/wonder+WH-(CLAUSE) (except for 'whether') | gộp → A2 `en.a2.indirect_question` |
| 194 | SENTENCE PATTERN: SUBJECT+V [AFF. DEC.] | ngoài phạm vi |
| 250 | FUNCTIONAL QUESTION: Could you ...? [AFF. INT.] | gộp → A2 `en.a2.can_you_request` |

### B2

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 10-1 | It is not [NEG. DEC.] | thiếu |
| 10-2 | Is it ...? [AFF. INT.] | thiếu |
| 20 | few PLURAL NOUN | gộp → B2 `en.b2.little_few` |
| 37-1 | COMPARISON OF EQUALITY: not as/so ... as [NEG. DEC./AFF. INT./NEG. DEC.] | gộp → B2 `en.b2.as_as` |
| 67-1 | TENSE/ASPECT: PAST PERFECT [NEG. DEC.] | gộp → B1 `en.b1.past_perfect` |
| 73-1 | PASSIVE: PRESENT [NEG. DEC.] | thiếu |
| 78 | PASSIVE: PAST PERFECT [AFF. DEC.] | gộp → B2 `en.b2.passive_perfect` |
| 82-1 | PASSIVE: AUX [NEG. DEC.] | gộp → B1 `en.b1.passive_modal` |
| 102 | VERB not to DO | gộp → B1 `en.b1.not_to` |
| 106 | not+V-ING | thiếu |
| 108 | being+PAST PARTICIPLE | thiếu |
| 123-1 | MODAL/AUX: can [NEG. DEC.] | gộp → A1 `en.can_ability` |
| 127-1 | MODAL/AUX: have to [NEG. DEC.] | gộp → A2 `en.a2.have_to` |
| 128 | MODAL/AUX: (have) got to [AFF. DEC.] | gộp → A2 `en.a2.have_to` |
| 129-1 | MODAL/AUX: may [NEG. DEC.] | gộp → B1 `en.b1.may` |
| 132-1 | MODAL/AUX: might | gộp → A2 `en.a2.might` |
| 142-1 | MODAL/AUX: would [NEG. DEC.] | gộp → A2 `en.a2.would_like` |
| 144 | AUX+PROGRESSIVE [AFF. DEC.] | thiếu |
| 145-1 | AUX+PERFECT [NEG. DEC.] | gộp → B2 `en.b2.modal_perfect` |
| 148 | there+AUX+be [AFF. DEC.] | gộp → B2 `en.b2.there_has_been` |
| 175 | ACCUSATIVE RELATIVE PRONOUN: who | gộp → B2 `en.b2.relative_object` |
| 176 | ACCUSATIVE RELATIVE PRONOUN: whom | gộp → B2 `en.b2.relative_object` |
| 177 | ACCUSATIVE RELATIVE PRONOUN: which | gộp → B2 `en.b2.relative_object` |
| 182 | PSEUDO RELATIVE PRONOUN: as | thiếu |
| 187 | RELATIVE ADVERB: NONRESTRICTIVE | thiếu |
| 193-1 | TAG QUESTION: FOLLOWING NEGATIVE SENTENCE [(MAIN CLAUSE) NEG. DEC.] | gộp → B1 `en.b1.tag_questions` |
| 210 | FEEL/HEAR/SEE+NP+INFINITIVE | gộp → B2 `en.b2.perception_verbs` |
| 237 | WH- QUESTION: Who ...? [AFF. INT./NEG. INT.] | thiếu |

### C1

Điểm dẫn mục của cấp khác hoặc mục không cấp: `en.c1.negative_inversion` ← 234 (không cấp); `en.c1.wish_past` ← 218 (không cấp); `en.c1.wish_past_perfect` ← 219 (không cấp); `en.c1.if_only` ← 222 (không cấp); `en.c1.as_if` ← 220 (không cấp); `en.c1.inverted_third_conditional` ← 226 (không cấp); `en.c1.if_it_were_not_for` ← 228 (không cấp); `en.c1.pseudo_cleft` ← 205 (không cấp); `en.c1.so_neither_do_i` ← 232 (không cấp); `en.c1.be_about_to` ← 100 (không cấp); `en.c1.may_well` ← 131 (không cấp); `en.c1.might_as_well` ← 133 (không cấp); `en.c1.would_rather` ← 143 (không cấp); `en.c1.dare` ← 125 (không cấp); `en.c1.possessive_gerund` ← 111 (không cấp); `en.c1.it_adjective_that` ← 165 (không cấp); `en.c1.by_the_time` ← 159 (không cấp); `en.c1.if_should` ← 224 (không cấp); `en.c1.perception_past_participle` ← 212 (không cấp); `en.c1.get_object_ing` ← 208 (không cấp); `en.c1.intensified_superlative` ← 52 (không cấp); `en.c1.future_perfect_progressive` ← 72 (không cấp); `en.c1.preposition_wh_question` ← 248 (không cấp).

Điểm DeepLingo tự thêm (danh mục không có): `en.c1.mixed_conditional`, `en.c1.high_time`, `en.c1.not_only_but_also`.

### C2

Điểm dẫn mục của cấp khác hoặc mục không cấp: `en.c2.inverted_were` ← 225 (không cấp); `en.c2.inverted_should` ← 227 (không cấp); `en.c2.were_it_not_for` ← 229 (không cấp); `en.c2.so_adjective_a_noun` ← 47 (không cấp); `en.c2.to_have_been_done` ← 92 (không cấp); `en.c2.having_been_done` ← 109 (không cấp).

Điểm DeepLingo tự thêm (danh mục không có): `en.c2.subjunctive`, `en.c2.fronting_inversion`, `en.c2.concessive_as`, `en.c2.no_matter`, `en.c2.were_to`, `en.c2.not_until_inversion`, `en.c2.absolute_construction`, `en.c2.nominal_that_clause`, `en.c2.the_adjective`, `en.c2.so_not_substitution`.

## Tiếng Trung (GF 0025-2021)

| Cấp | Điểm trong file | Mục danh mục ở cấp này | Trực tiếp | Gộp | Ở cấp khác | Ngoài phạm vi | Thiếu |
|---|---|---|---|---|---|---|---|
| HSK1 | 19 | 48 | 19 | 0 | 0 | 9 | 20 |
| HSK2 | 43 | 82 | 43 | 7 | 0 | 7 | 25 |
| HSK3 | 41 | 81 | 41 | 6 | 0 | 4 | 30 |
| HSK4 | 40 | 76 | 40 | 0 | 0 | 4 | 32 |
| HSK5 | 37 | 71 | 37 | 2 | 0 | 5 | 27 |
| HSK6 | 31 | 67 | 31 | 2 | 0 | 2 | 32 |

### HSK1

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 10 | 副词 范围、协同副词 都1、一块儿、一起 | thiếu |
| 11 | 副词 时间副词 马上、先、有时、在、正、正在 | thiếu |
| 12 | 副词 频率、重复副词 常、常常、再1 | thiếu |
| 13 | 副词 关联副词 还1、也 | thiếu |
| 14 | 副词 否定副词 别、不、没、没有 | thiếu |
| 15 | 介词 引出时间、处所 从1 | thiếu |
| 17 | 介词 引出对象 跟1、和1 | thiếu |
| 18 | 介词 引出对象 比 | thiếu |
| 19 | 连词 连接词或词组 跟2、还是、和2 | thiếu |
| 20 | 助词 结构助词 的1、地 | thiếu |
| 21 | 助词 动态助词 了1 | thiếu |
| 22 | 助词 语气助词 吧1、了2、吗、呢 | thiếu |
| 23 | 结构类型 其他结构类型 数量短语 | ngoài phạm vi |
| 24 | 主语 名词、代词或名词性短语作主语 | ngoài phạm vi |
| 25 | 谓语 动词或动词性短语、形容词或形容词性短语作谓语 | ngoài phạm vi |
| 26 | 宾语 名词、代词或名词性短语作宾语 | ngoài phạm vi |
| 27 | 定语 名词性词语、形容词性词语、数量短语作定语 | ngoài phạm vi |
| 28 | 状语 副词、形容词作状语； 表示时间、处所的词语作状语 | ngoài phạm vi |
| 29 | 句型 单句 主谓句1：动词谓语句 | ngoài phạm vi |
| 31 | 句型 单句 非主谓句 | ngoài phạm vi |
| 32 | 句类 陈述句 陈述句 | ngoài phạm vi |
| 33 | 句类 疑问句 （1）是非问句（2）特指问句（3）选择问句（4）正反问句 | thiếu |
| 34 | 句类 祈使句 祈使句 | thiếu |
| 35 | 句类 感叹句 感叹句 | thiếu |
| 38 | 特殊句型 比较句 比较句1：（1）A比B +形容词（2）A没有B +形容词 | thiếu |
| 39 | 复句 并列复句 （1）不用关联词语 （2）用关联词语：一边……，一边……；……，也…… | thiếu |
| 40 | 动作的态 变化态 用语气助词“了2”表示 | thiếu |
| 41 | 动作的态 完成态 用动态助词“了1”表示 | thiếu |
| 47 | 用“还是”提问 | thiếu |

### HSK2

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 56 | 形容词 形容词重叠 AA、AABB | thiếu |
| 57 | 数词 千、万、亿 | thiếu |
| 58 | 量词 名量词 层、封、件、条、位 | thiếu |
| 60 | 量词 时量词 分钟、年、天、周 | thiếu |
| 66 | 副词 方式副词 故意 | thiếu |
| 69 | 介词 引出时间、处所 当 | thiếu |
| 71 | 介词 引出方向、路径 向1 | thiếu |
| 72 | 介词 引出方向、路径 从2 | thiếu |
| 76 | 介词 引出目的、原因 为1 | thiếu |
| 77 | 连词 连接词或词组 或、或者 | thiếu |
| 78 | 连词 连接分句或句子 不过、但、但是、而且、那、如果、虽然、只要 | gộp → HSK2 `zh.hsk2.suiran_danshi` |
| 79 | 助词 结构助词 得 | gộp → HSK2 `zh.hsk2.state_complement` |
| 80 | 助词 动态助词 过 | gộp → HSK2 `zh.hsk2.guo_experience` |
| 81 | 助词 着 | gộp → HSK2 `zh.hsk2.zhe_continuous` |
| 82 | 助词 语气助词 啊1、吧2、的2 | thiếu |
| 83 | 助词 其他助词 的话、等 | thiếu |
| 84 | 叹词 喂 | thiếu |
| 85 | 结构类型 基本结构类型 基本结构类型：（1）联合短语（2）偏正短语（3）动宾短语（4）动补短语（5）主谓短语 | ngoài phạm vi |
| 86 | 结构类型 其他结构类型 其他结构类型1：（1）“的”字短语（2）连谓短语 | ngoài phạm vi |
| 87 | 功能类型 名词性短语 | ngoài phạm vi |
| 88 | 功能类型 动词性短语 | ngoài phạm vi |
| 89 | 功能类型 形容词性短语 | ngoài phạm vi |
| 90 | 固定短语 其他 不一会儿 | thiếu |
| 91 | 固定短语 其他 什么的 | thiếu |
| 93 | 还是……吧 | thiếu |
| 96 | 谓语 名词、代词、数词、数量短语、名词性短语作谓语 | ngoài phạm vi |
| 100 | 补语 数量补语 数量补语1：动词+动量补语 | gộp → HSK2 `zh.hsk2.verbal_measure_words` |
| 101 | 补语 数量补语 数量补语2：形容词+数量补语 | thiếu |
| 102 | 句型 单句 主谓句3：名词谓语句 | ngoài phạm vi |
| 103 | 特殊句型 “有”字句 “有”字句2：（1）表示评价、达到； （2）表示比较（见“比较句 2-（4）”） | thiếu |
| 104 | 特殊句型 存现句 存现句1：表示存在 （1）处所+有+数量短语+名词（见“‘有’字句1-（2）”） （2）处所+动词+着（+数量短语）+名词 | gộp → HSK2 `zh.hsk2.zhe_continuous` |
| 112 | 复句 选择复句 （1）不用关联词语（2）用关联词语：（是）……，还是…… | thiếu |
| 120 | 数的表示法 序数表示法 | thiếu |
| 121 | 数的表示法 概数表示法1： （1）数词+多+量词（2）数词+量词+多 | thiếu |
| 122 | 用“就”表示强调 | thiếu |
| 123 | ※“是……的”表示强调（见“是……的”句1和“是……的”句2）) | gộp → HSK2 `zh.hsk2.shi_de` |
| 125 | 用“什么时候、什么样、为什么、怎么样、怎样”提问 | thiếu |
| 127 | 用“是不是”提问 | thiếu |
| 128 | 用“吧”提问 | thiếu |

### HSK3

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 131 | 前缀 第-、老-、小- | thiếu |
| 132 | 后缀 -儿、-家、-们、-头、-子 | thiếu |
| 136 | 动词 离合词 动补式离合词：打开、看见、离开、完成 | thiếu |
| 140 | 量词 动量词 顿、口、眼 | thiếu |
| 141 | 量词 量词重叠 量词重叠：AA | thiếu |
| 146 | 副词 关联副词 再2 | thiếu |
| 150 | 介词 引出时间、处所 由1 | thiếu |
| 152 | 介词 引出方向、路径 朝 | thiếu |
| 153 | 介词 引出对象 为2 | thiếu |
| 154 | 介词 引出对象 向2 | thiếu |
| 155 | 介词 引出目的、原因 由于1、因为 | gộp → HSK3 `zh.hsk3.youyu_yinci` |
| 157 | 介词 引出施事、受事 把、被、叫、让 | gộp → HSK3 `zh.hsk3.ba_sentence` |
| 158 | 介词 表示排除 除了 | gộp → HSK3 `zh.hsk3.chule` |
| 160 | 连词 连接分句或句子 并且、不光、不仅、另外、要是、因此、由于2、只有 | gộp → HSK3 `zh.hsk3.bujin_hai` |
| 161 | 拟声词 哈哈 | thiếu |
| 162 | 结构类型 其他结构类型 其他结构类型2：（1）介宾短语（2）方位短语（3）兼语短语（4）同位短语 | thiếu |
| 163 | 结构类型 数量重叠：数词+量词+数词+量词 | thiếu |
| 164 | 固定短语 四字格 不A不B | thiếu |
| 166 | 固定短语 其他 看上去 | gộp → HSK3 `zh.hsk3.kanqilai` |
| 167 | 固定短语 其他 有的是 | thiếu |
| 169 | 从……起 | thiếu |
| 173 | 主语 动词或动词性短语、形容词或形容词性短语作主语 | ngoài phạm vi |
| 174 | 宾语 动词或动词性短语、形容词或形容词性短语和主谓短语作宾语 | ngoài phạm vi |
| 175 | 定语 动词或动词性短语、主谓短语作定语 | ngoài phạm vi |
| 180 | 补语 数量补语 数量补语 3（动词+动量补语）：宾语和动量补语共现 | thiếu |
| 182 | 补语 数量补语 数量补语5（动词+时量补语）：表示动作结束后到某个时间点的间隔时间 | thiếu |
| 183 | 句型 单句 主谓句4：主谓谓语句 | ngoài phạm vi |
| 186 | 特殊句型 连动句 连动句2： （1）前一动作是后一动作的方式（2）后一动作是前一动作的目的 | thiếu |
| 189 | 特殊句型 重动句 主语+动词+宾语+动词+补语 | thiếu |
| 190 | 复句 并列复句 （也）……，也…… | thiếu |
| 193 | 复句 并列复句 又……，又…… | thiếu |
| 195 | 复句 递进复句 ……，并且…… | thiếu |
| 198 | 复句 转折复句 ……X是X，就是/不过…… | thiếu |
| 202 | 复句 目的复句 为了……，…… | gộp → HSK3 `zh.hsk3.weile` |
| 203 | 复句 紧缩复句 ……了……（就）…… | thiếu |
| 204 | 数的表示法 概数表示法2： （1）用“大概、大约、几”表示概数（2）相邻数词连用表示概数（3）用“左右、前后”表示概数 | thiếu |
| 207 | 用“是”表示强调 | thiếu |
| 208 | 用疑问语调表示疑问 | thiếu |
| 210 | X就X（点儿）吧 | thiếu |
| 211 | X什么（啊） | thiếu |

### HSK4

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 213 | 代词 人称代词 人家 | thiếu |
| 214 | 量词 名量词 打、袋、根、卷、棵、批 | thiếu |
| 215 | 量词 借用量词 （1）名量词：碗、脸、手、屋子、桌子 （2）动量词：刀、针 | thiếu |
| 217 | 副词 范围、协同副词 共 | thiếu |
| 219 | 副词 频率、重复副词 一再、再三 | thiếu |
| 224 | 介词 引出时间、处所 自 | thiếu |
| 230 | 连词 连接词或词组 并2、以及 | thiếu |
| 233 | 叹词 啊2 | thiếu |
| 234 | 固定短语 四字格 大A大B | thiếu |
| 235 | 固定短语 四字格 一A一B | thiếu |
| 240 | 一+量词+比+一+量词 | thiếu |
| 242 | 由……组成 | thiếu |
| 244 | 在……上/下/中 | thiếu |
| 245 | 主语 主谓短语作主语 | ngoài phạm vi |
| 246 | 主语 受事主语 | ngoài phạm vi |
| 247 | 定语 多项定语 | ngoài phạm vi |
| 251 | 特殊句型 存现句 存现句2： （1）表示出现：处所词+动词+趋向补语/结果补语+动态助词（了）+数量短语+人/物（2）表示消失：处所词+动词+结果补语+动态助词 | thiếu |
| 256 | 复句 承接复句 首先……，其次…… | thiếu |
| 259 | 复句 选择复句 或者……，或者…… | thiếu |
| 262 | 复句 假设复句 假如……，（就）…… | thiếu |
| 267 | 复句 因果复句 ……，可见…… | thiếu |
| 269 | 复句 目的复句 ……，好…… | thiếu |
| 270 | 复句 紧缩复句 无标记 | ngoài phạm vi |
| 271 | 复句 紧缩复句 不……也…… | thiếu |
| 272 | 数的表示法 概数表示法3：数词+来+量词 | thiếu |
| 276 | 用“一+量词（+名词）+也（都）/也没（不）……”表示强调 | thiếu |
| 278 | 不X白不X | thiếu |
| 279 | 动词+一X是一X | thiếu |
| 280 | （没）有什么（好）X的 | thiếu |
| 281 | X是X，Y是Y | thiếu |
| 282 | X也得X，不X也得X | thiếu |
| 283 | X就是了 | thiếu |
| 284 | 还X呢 | thiếu |
| 285 | 你X你的吧 | thiếu |
| 286 | 让/叫你X你就X | thiếu |
| 287 | 说什么/怎么（着）也得X | thiếu |

### HSK5

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 289 | 量词 名量词 册、朵、幅、届、颗、匹、扇 | thiếu |
| 291 | 副词 范围、协同副词 大都 | thiếu |
| 294 | 副词 方式副词 偷偷 | thiếu |
| 300 | 介词 引出凭借、依据 依据 | gộp → HSK5 `zh.hsk5.yizhao` |
| 305 | 固定短语 四字格 A着A着 | thiếu |
| 306 | 固定短语 四字格 没A没B | thiếu |
| 307 | 固定短语 四字格 说A就A | thiếu |
| 308 | 固定短语 四字格 有A有B | thiếu |
| 310 | 固定短语 其他 不敢当 | thiếu |
| 311 | 固定短语 其他 得了 | thiếu |
| 315 | 够……的 | thiếu |
| 317 | A的A，B的B | thiếu |
| 319 | 宾语 宾语的语义类型1：（1）施事宾语；（2）受事宾语 | ngoài phạm vi |
| 320 | 状语 多项状语 | ngoài phạm vi |
| 326 | 特殊句型 “把”字句 “把”字句3：表处置 （1）主语+把+宾语+状语+动词 （2）主语+把+宾语+一+动词 （3）主语+把+宾语+动词+了 （4）主语+把+宾 | thiếu |
| 328 | 特殊句型 连动句 连动句3：前后两个动词性词语具有因果、转折、条件关系 | thiếu |
| 331 | 复句 选择复句 或是……，或是…… | thiếu |
| 334 | 复句 假设复句 要是……，（就）……，否则…… | thiếu |
| 336 | 复句 条件复句 除非……，否则/不然…… | gộp → HSK5 `zh.hsk5.chufei` |
| 341 | 复句 紧缩复句 没有……就没有…… | thiếu |
| 343 | 复句 多重复句 二重复句1：单句+复句；复句+单句 | ngoài phạm vi |
| 345 | 用副词“可”表示强调 | thiếu |
| 347 | X也不是，Y也不是 | thiếu |
| 348 | X也X不得，Y也Y不得 | thiếu |
| 349 | X是它，Y也是它 | thiếu |
| 350 | X着也是X着 | thiếu |
| 351 | X归X，Y归Y | thiếu |
| 352 | 不管怎样说 | thiếu |
| 353 | 看你X的/瞧他X的 | thiếu |
| 354 | 真有你/他/她的 | thiếu |
| 355 | X什么X | thiếu |
| 356 | 什么X不X（的） | thiếu |
| 357 | 形式分类 用代词复指 （1）用人称代词复指（2）用指示代词复指（3）各种代词相间使用 | ngoài phạm vi |
| 358 | 形式分类 带省略成分 （1）省略主语（2）省略宾语 | ngoài phạm vi |

### HSK6

| Mục | Nội dung (nhãn ngắn) | Trạng thái |
|---|---|---|
| 359 | 前缀 类前缀：超-、多-、反-、无-、亚-、准- | gộp → HSK6 `zh.hsk6.suffixes` |
| 362 | 量词 名量词 餐、串、滴、副、股、集、枝 | thiếu |
| 363 | 量词 动量词 番、声、趟 | thiếu |
| 364 | 副词 程度副词 特、异常 | thiếu |
| 376 | 介词 表示排除 除 | thiếu |
| 378 | 连词 连接词或词组 而2、同2、与2 | thiếu |
| 382 | 结构类型 基本结构类型 数词+形容词+量词 | thiếu |
| 383 | 固定短语 四字格 或A或B | thiếu |
| 384 | 固定短语 四字格 无A无B | thiếu |
| 385 | 固定短语 四字格 A这A那 | thiếu |
| 386 | 固定短语 四字格 左A右B | thiếu |
| 388 | 固定短语 其他 不怎么样 | thiếu |
| 390 | 固定短语 其他 那倒（也）是 | thiếu |
| 393 | A一+量词，B一+量词 | thiếu |
| 394 | 东一A，西一A | thiếu |
| 396 | 宾语 宾语的语义类型2： （1）处所宾语（2）结果宾语 | ngoài phạm vi |
| 400 | 复句 并列复句 时而……，时而…… | thiếu |
| 401 | 复句 并列复句 一时……一时…… | thiếu |
| 402 | 复句 承接复句 ……便…… | gộp → HSK6 `zh.hsk6.bian` |
| 404 | 复句 递进复句 不是……，还/还是…… | thiếu |
| 405 | 复句 递进复句 连……都/也……，……更…… | thiếu |
| 408 | 复句 假设复句 ……，要不然/不然…… | thiếu |
| 411 | 复句 紧缩复句 不……不…… | thiếu |
| 412 | 复句 多重复句 二重复句2：复句+复句 | ngoài phạm vi |
| 414 | X到Y头上来了 | thiếu |
| 415 | X就X吧 | thiếu |
| 416 | X是X | thiếu |
| 417 | 不X不……，一X…… | thiếu |
| 418 | 好你个X | thiếu |
| 419 | 动词+什么（就）是什么 | thiếu |
| 420 | 早（也）不X，晚（也）不X | thiếu |
| 421 | 看/瞧+把+宾语（施事）+ X 得 | thiếu |
| 422 | 放着X不Y | thiếu |
| 423 | X来X去，都是/就是 …… | thiếu |
| 424 | X了就X了，（没）有…… | thiếu |
| 425 | 这/那也不X，那/这也不Y | thiếu |

