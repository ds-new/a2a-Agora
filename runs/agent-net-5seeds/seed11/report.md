# Agora agent-network simulation report

43 agents, 12 rounds, transport `memory`, seed 11.

## Totals

| metric | value |
|---|---|
| gmv | 2999.51 |
| deals_completed | 77 |
| deals_refunded | 6 |
| platform_fee | 0.0 |
| escrow_fees | 15.0 |
| referral_payouts | 6.18 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 122 |
| needs_created | 73 |
| a2a_messages | 4769 |
| intents | 4 |
| forwards | 342 |
| blocks | 18 |
| subscriptions | 71 |
| honest_proposals | 433 |
| honest_acceptance | 0.7436 |
| reputation_vs_quality_spearman | 0.251 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5114 | 0.6332 | 0.0237 | 2.63 | 0.758 | 0.0 | 3.58 | 19.77 |
| base skills only | 12 | 0.4874 | 0.5876 | 0.0547 | 1.9 | 0.759 | 0.0 | 2.83 | 14.93 |

Rejection reasons the agents sent back: with X skills: {'off-topic': 33, 'attention-budget': 16, 'disliked-category': 3, 'unsafe': 70, 'too-expensive': 19, 'blocked': 1}; base skills only: {'off-topic': 12, 'not-shippable': 13, 'unsafe': 54, 'too-expensive': 4}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.869 after learning vs 0.884 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 0.775 | 45.3 |
| subscribers | 8 | 0.714 | 23.5 |
| private | 3 | 0.75 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.341 / 0.220 | 0.50 / 0.36 | 0.8889 | 9 | 36 | 918 |
| 1 | 0.521 / 0.456 | 0.69 / 0.50 | 0.8182 | 55 | 36 | 497 |
| 2 | 0.477 / 0.543 | 0.58 / 0.66 | 0.7963 | 54 | 43 | 437 |
| 3 | 0.510 / 0.471 | 0.62 / 0.57 | 0.7391 | 46 | 23 | 315 |
| 4 | 0.516 / 0.510 | 0.78 / 0.52 | 0.7551 | 49 | 30 | 373 |
| 5 | 0.574 / 0.543 | 0.68 / 0.74 | 0.7073 | 41 | 24 | 320 |
| 6 | 0.429 / 0.526 | 0.48 / 0.70 | 0.8462 | 13 | 25 | 273 |
| 7 | 0.626 / 0.380 | 0.62 / 0.65 | 0.0 | 5 | 24 | 200 |
| 8 | 0.569 / 0.492 | 0.74 / 0.38 | 0.7778 | 9 | 24 | 235 |
| 9 | 0.575 / 0.502 | 0.57 / 0.58 | 0.75 | 52 | 24 | 357 |
| 10 | 0.571 / 0.548 | 0.66 / 0.81 | 0.6545 | 55 | 24 | 451 |
| 11 | 0.465 / 0.516 | 0.62 / 0.53 | 0.7333 | 45 | 24 | 393 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pagehouse | physical | True | 0.626 | 4 | 1.0 | 0 | 4 | 0 | 76.6 | 0 | 0.489 | - |
| loomworks | physical | True | 0.812 | 2 | 1.0 | 0 | 1 | 0 | 38.17 | 0 | 0.15 | - |
| inference-weekly | information | True | 0.681 | 26 | 0.923 | 0 | 1 | 0 | 4.58 | 0 | 0.163 | - |
| ridgeline | physical | True | 0.804 | 55 | 0.855 | 0 | 19 | 0 | 901.57 | 0 | 1.0 | - |
| lab-notes | information | True | 0.713 | 45 | 0.844 | 0 | 3 | 0 | 15.92 | 0 | 0.483 | - |
| hearth | physical | True | 0.574 | 38 | 0.842 | 0 | 18 | 0 | 493.58 | 0 | 0.841 | - |
| voltmart | physical | True | 0.588 | 45 | 0.822 | 0 | 14 | 0 | 1226.31 | 0 | 0.895 | - |
| macro-desk | information | True | 0.806 | 74 | 0.662 | 0 | 0 | 0 | 0 | 0 | 0.643 | - |
| wok-and-whisk | information | True | 0.775 | 78 | 0.654 | 0 | 8 | 0 | 26.87 | 0 | 0.804 | - |
| pitchside | information | True | 0.833 | 56 | 0.607 | 0 | 1 | 0 | 5.15 | 0 | 0.553 | - |
| alpha-leaks | information | False | 0.25 | 49 | 0.583 | 1 | 0 | 1 | 0 | 0 | 0.0 | fraud |
| beanery | physical | True | 0.893 | 10 | 0.4 | 0 | 8 | 0 | 189.58 | 0 | 0.597 | - |
| brandz-outlet | physical | False | 0.05 | 337 | 0.056 | 14 | 0 | 5 | 0 | 0 | 0.0 | scam-risk |

## Sample decisions (with the reasons agents recorded)

- `accept` water filter: exploring 'outdoor', which the principal never rated (picked by x_rank)
- `reject` Premium portable ssd: flagged by a subscribed labeler / safety rules
- `accept` commodities note: principal's interest in 'markets' is 0.80; utility 0.71; recommended by a friend
- `accept` commodities note: principal's interest in 'markets' is 0.69; utility 0.60
- `accept` knife skills guide: principal's interest in 'cooking' is 0.75; utility 0.71
- `accept` commodities note: principal's interest in 'markets' is 0.71; utility 0.62
- `accept` water filter: principal's interest in 'outdoor' is 0.68; utility 0.61; x_rank position 3
- `accept` fusion progress recap: exploring 'science', which the principal never rated (picked by x_rank)
- `reject` sourdough troubleshooting: relevant, but attention for this tick is used up
- `accept` sourdough troubleshooting: principal's interest in 'cooking' is 0.60; utility 0.60; recommended by a friend
- `accept` weeknight noodle recipes: principal's interest in 'cooking' is 0.60; utility 0.58; recommended by a friend
- `accept` espresso blend: principal's interest in 'coffee' is 0.89; utility 0.58
