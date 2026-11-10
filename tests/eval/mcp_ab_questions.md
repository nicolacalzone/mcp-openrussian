# OpenRussian MCP — A/B question set (100 items)

Run every item twice: **MCP off** (model alone) and **MCP on** (openrussian tools enabled).
Grade blind against the "Expected / check" column.

## Protocol

| Metric | How |
|---|---|
| Correctness | 0 / 0.5 / 1 against the reference answer |
| Hallucination | Invented form, stress, entry or example sentence = 1 |
| Tool use (MCP on) | Which tools were called; were they necessary? |
| Cost | Tool calls, tokens, latency |

Run each item 3 times if you can. The model is non-deterministic, so one run proves little.

## Hypotheses per group

| Group | Items | Expected MCP effect |
|---|---|---|
| A. Spelling and unknown words | 10 | Strong gain: `analyze_text` flags `unknown` words |
| B. Stress | 10 | Strong gain: dictionary stress marks |
| C. Inflection tables | 10 | Strong gain: full forms |
| D. Aspect and motion verbs | 10 | Medium gain: aspect pairs |
| E. Government (case after verb or preposition) | 10 | Medium gain: government notes |
| F. Meaning, lexis, false friends | 10 | Medium; the dictionary may lack colloquial or archaic words |
| G. Frequency, CEFR, study lists | 10 | Very strong gain: the model has no ground truth without data |
| H. Example sentences | 8 | Strong gain: Tatoeba examples |
| I. Sentence correction | 10 | Small to medium: the MCP checks words, not syntax |
| J. C2 intricate questions | 12 | **Control group**: little or none; watch for the MCP *hurting* |

---

## A. Spelling and unknown words (`analyze_text`)

| ID | Prompt | Expected / check |
|---|---|---|
| A01 | Check this: «Я хачу купить новую машыну.» | хочу, машину |
| A02 | Check this: «Вчера мы ужинали в рестаране.» | ресторане |
| A03 | Check this: «Она живёт в Масскве.» | Москве |
| A04 | Check this: «Я не знаю, кто пришол.» | пришёл (or пришел) |
| A05 | Check this: «Пожалуйста, пирепишите этот текст.» | перепишите |
| A06 | Is «ихние» correct in «Ихние дети уже выросли»? | Substandard or colloquial; standard form is «их дети». Do not confuse "unknown" with "wrong". |
| A07 | Check this: «Сколько стоит этот ноутбук? Мне нужен подешевле.» | **No errors** (false-positive control) |
| A08 | Check this: «Он пишет диссертацию по лингвестике.» | лингвистике |
| A09 | Check this: «Мы ждём вас в пять часов, не опаздайте!» | опоздайте |
| A10 | Check this: «Я учу русский язык уже три годa.» (the final «a» is a **Latin** letter) | Detect the homoglyph; годa → года |

## B. Stress (ударение)

| ID | Prompt | Expected / check |
|---|---|---|
| B01 | Where is the stress in «звонишь»? | звони́шь (звоню́, звони́т) |
| B02 | Stress in the plural «торты»? | то́рты (OpenRussian and current usage). Also accept торты́ as the older prescriptive variant. Full marks need the answer to say which is which |
| B03 | Stress in «красивее»? | краси́вее |
| B04 | Stress in «договор», singular and plural? | догово́р, договоры́ (prescriptive norm). OpenRussian lists догово́ры; an answer should give the norm and may note the dictionary variant |
| B05 | Stress in «щавель»? | щаве́ль |
| B06 | Stress in «кухонный»? | ку́хонный |
| B07 | Stress in «включит»? | включи́т |
| B08 | Stress in «средства»? | сре́дства |
| B09 | Stress in «столяр»? | столя́р |
| B10 | Stress in «квартал»? | кварта́л |

## C. Inflection tables

| ID | Prompt | Expected / check |
|---|---|---|
| C01 | Genitive plural of «яблоко»? | яблок |
| C02 | Genitive plural of «носок» and «чулок»? | носков; чулок (zero ending) |
| C03 | «Where?» form of «лес» (в лесу или в лесе)? | в лесу́ (locative -у) |
| C04 | Imperative of «лечь»? | ляг, лягте |
| C05 | Past tense of «мочь», all genders and plural? | мог, могла́, могло́, могли́ |
| C06 | Comparatives of хороший, плохой, большой, маленький? | лучше, хуже, больше, меньше |
| C07 | Genitive plural of «ребёнок» and «человек»? | детей (ребят); людей, but «пять человек» after numerals |
| C08 | Instrumental of «мать» and «дочь»? | матерью, дочерью |
| C09 | Full present tense of «хотеть»? | хочу, хочешь, хочет, хотим, хотите, хотят (mixed conjugation) |
| C10 | Decline «путь». | masc., but instrumental путём; gen/dat/prep пути |

## D. Aspect and motion verbs

| ID | Prompt | Expected / check |
|---|---|---|
| D01 | Perfective of «читать»? | прочитать (also почитать, different meaning) |
| D02 | Imperfective partner of «решить»? | решать |
| D03 | Which of «покупать» / «купить» is perfective? | купить |
| D04 | Imperfective of «взять»? | брать (suppletive-looking pair) |
| D05 | Difference between «идти» and «ходить»? | determinate vs indeterminate motion |
| D06 | Fill in: «Я каждый день ___ в университет пешком.» | хожу |
| D07 | Aspect of «использовать»? | Biaspectual (the dictionary labels it `both`; confirmed against the data) |
| D08 | Perfective of «стоять»? | No true pair; постоять is delimitative («stand for a while») |
| D09 | Fill in: «Сегодня утром он ___ из дома в восемь.» | вышел (в- vs вы-) |
| D10 | «Не открывай окно» or «Не открой окно»? | Negative imperative takes imperfective; the perfective is a warning («Смотри, не открой!») |

## E. Government (case after verb or preposition)

| ID | Prompt | Expected / check |
|---|---|---|
| E01 | Case after «бояться»? | genitive (боюсь собак, темноты) |
| E02 | Case after «заниматься»? | instrumental (спортом) |
| E03 | «Скучать по» takes which case? | dative (по тебе) |
| E04 | Case after «интересоваться»? | instrumental |
| E05 | «Отвечать на» takes which case? | accusative (на вопрос) |
| E06 | «Жаловаться на» takes which case? | accusative |
| E07 | «Ждать» + accusative or genitive? | Both: ждать автобус (specific) / автобуса, письма; «дожидаться» + genitive |
| E08 | Case after «пользоваться»? | instrumental |
| E09 | «Платить за» vs «оплатить»: government? | платить за + acc; оплатить + acc (оплатить счёт) |
| E10 | «В» or «на»: аэропорт, вокзал, работа, почта, школа, кухня? | в аэропорту; на вокзале; на работе; на почте; в школе; на кухне |

## F. Meaning, lexis, false friends

| ID | Prompt | Expected / check |
|---|---|---|
| F01 | «Одеть» or «надеть»: when to use which? | надеть (что) на себя; одеть (кого) |
| F02 | Is «ложить» a word? | Non-standard; use класть / положить |
| F03 | What does «фамилия» mean? (false friend) | surname, not «family» |
| F04 | Difference between «адресат» and «адресант»? | recipient / sender |
| F05 | Meaning of «подсобить»? | colloquial: to help out |
| F06 | Give synonyms of «говорить» with register notes. | сказать, рассказать, болтать, молвить, etc. |
| F07 | Meanings of «замок» and «мука» depending on stress. | зА́мок (castle) / замо́к (lock); му́ка (torment) / мука́ (flour) |
| F08 | Difference between «авось» and «небось»? | авось: «maybe, hoping for luck»; небось: «probably, I bet» |
| F09 | Explain «тоска» to a learner. | longing, melancholy, boredom, anguish |
| F10 | What does «давеча» mean? | colloquial or dialect: «the other day, a while ago» |

## G. Frequency, CEFR level, study lists (`browse_entries`)

For this group the reference answer is the MCP's data: `ground_truth_G.md`, computed from the dictionary by `tools/ground_truth_g.py`. Without the MCP, check whether the model is confident but wrong. The dictionary has no topic tags, so G05, G07 and G09 are judged on plausibility and on whether the words are tagged at the requested level.

| ID | Prompt | Expected / check |
|---|---|---|
| G01 | List the 10 most frequent Russian nouns. | See `ground_truth_G.md` (computed by `tools/ground_truth_g.py`) |
| G02 | Give me 15 B1 verbs. | Verbs actually tagged B1 |
| G03 | What CEFR level is «ответственность»? | Dictionary level |
| G04 | Which is more frequent, «видеть» or «смотреть»? | Compare ranks |
| G05 | A1 vocabulary about food, 20 words. | Words tagged A1 and food |
| G06 | What is the frequency rank of «авось»? | Real rank, or «not ranked» |
| G07 | 20 B2 adjectives describing character. | B2 level adjectives |
| G08 | Is «чайник» a common word? What level? | Rank and level |
| G09 | List family-related words from the dictionary. | Use the topic tag |
| G10 | 10 C1 words that rarely appear in conversation. | Dictionary level; the MCP may be weak at register |

## H. Example sentences (`find_examples`)

| ID | Prompt | Expected / check |
|---|---|---|
| H01 | Example sentences with «несмотря на». | Real Tatoeba sentences |
| H02 | Example sentences with «скучать по». | Check the case after «по» |
| H03 | Examples of «хотя бы». | Natural sentences |
| H04 | Examples of «вместо» + genitive. | Real sentences |
| H05 | Examples with «обязательно». | Real sentences |
| H06 | Examples of «пожалуйста»: request vs reply to «спасибо». | Both uses shown |
| H07 | Examples of the imperative of «взять». | возьми(те) |
| H08 | Examples of «ходить» in the past tense. | ходил, ходила, ходили |

## I. Sentence correction

| ID | Prompt | Expected / check |
|---|---|---|
| I01 | Correct: «Я скучаю тебя.» | Я скучаю по тебе. |
| I02 | Correct: «Мы с братом пошли на кино.» | в кино |
| I03 | Correct: «Вчера я одел новую куртку.» | надел |
| I04 | Correct: «Он очень боится от собак.» | боится собак |
| I05 | Correct: «Она хорошо говорит по-русски, чем я.» | говорит по-русски лучше, чем я |
| I06 | Correct: «У меня нету времени.» | нет (нету is colloquial) |
| I07 | Correct: «Я хочу, чтобы ты пойдёшь со мной.» | чтобы ты пошёл |
| I08 | Correct: «Он сказал что он придёт.» | Он сказал, что придёт. |
| I09 | Correct: «Мне двадцать два годов.» | двадцать два года |
| I10 | Correct: «Встретимся завтра в 5 часа.» | в пять часов |

## J. C2 intricate questions (control group)

| ID | Prompt | Expected / check |
|---|---|---|
| J01 | Give all participle and gerund forms of «писать» / «написать». | пишущий, писавший, писанный; написанный; пиша, написав |
| J02 | What is wrong with «Идя по улице, у него упала шляпа»? Fix it. | Dangling gerund: the gerund's subject must match the main subject. «Идя по улице, он уронил шляпу.» |
| J03 | Comma in «Несмотря на то что шёл дождь…»: where? Compare «невзирая на». | Modern norm: no comma inside the compound conjunction (optional with logical stress). |
| J04 | Genitive of negation: «не читал эту книгу» vs «не читал этой книги»? When is it obligatory? | Mandatory: нет времени, не было никого; optional with transitive verbs. |
| J05 | Decline «пятьсот восемьдесят три» in the genitive and instrumental. | пятисот восьмидесяти трёх; пятьюстами восьмьюдесятью (or восемьюдесятью) тремя |
| J06 | Difference between the particles in «Ты-то что думаешь?» and «Ты же знаешь». | -то: contrast or topic; же: «but you know»; ведь: justification |
| J07 | How does stress change the meaning of «Я вчера купил книгу»? | Communicative stress: each word placed in focus gives a different implication |
| J08 | When do you use «бы» vs «чтобы»? Same subject or different subject? | Same subject: infinitive; different subject: past tense after чтобы |
| J09 | Case after «благодаря», «вопреки», «согласно»; and after «по прибытии»? | dative; «по прибытии» takes prepositional |
| J10 | Gender of «кофе», «пальто», «кенгуру», «шампунь», «тюль». | masc.; neuter; masc.; masc.; masc. (кофе is also tolerated as neuter in colloquial speech) |
| J11 | Explain impersonal constructions: «Меня тошнит», «Мне не спится», «Его убило молнией». | Dative or accusative experiencer, neuter or 3sg verb, no nominative subject |
| J12 | Fused vs split: ввиду/в виду, вследствие/в следствие, насчёт/на счёт, зато/за то, тоже/то же. | Fused: prepositions or conjunctions; split: preposition + noun or pronoun |
