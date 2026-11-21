# Agora agent-network simulation report

43 agents, 12 rounds, transport `memory`, seed 10.

## Totals

| metric | value |
|---|---|
| gmv | 2979.59 |
| deals_completed | 98 |
| deals_refunded | 9 |
| platform_fee | 0.0 |
| escrow_fees | 14.9 |
| referral_payouts | 11.27 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 131 |
| needs_created | 69 |
| a2a_messages | 4804 |
| intents | 1 |
| forwards | 277 |
| blocks | 23 |
| subscriptions | 76 |
| honest_proposals | 402 |
| honest_acceptance | 0.687 |
| reputation_vs_quality_spearman | 0.223 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5567 | 0.6854 | 0.0506 | 2.47 | 0.84 | 0.0 | 5.0 | 54.41 |
| base skills only | 12 | 0.532 | 0.7186 | 0.0519 | 1.6 | 0.821 | 0.0 | 3.17 | 20.68 |

Rejection reasons the agents sent back: with X skills: {'off-topic': 22, 'attention-budget': 36, 'disliked-category': 1, 'too-expensive': 5, 'unsafe': 83, 'blocked': 1}; base skills only: {'disliked-category': 5, 'off-topic': 14, 'too-expensive': 4, 'attention-budget': 3, 'unsafe': 45, 'not-shippable': 24}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.878 after learning vs 0.903 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 0.897 | 43.8 |
| subscribers | 8 | 0.737 | 22.4 |
| private | 3 | 0.8 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.477 / 0.215 | 0.71 / 0.43 | 1.0 | 15 | 33 | 958 |
| 1 | 0.467 / 0.462 | 0.58 / 0.65 | 0.82 | 50 | 51 | 532 |
| 2 | 0.604 / 0.548 | 0.73 / 0.71 | 0.7778 | 45 | 31 | 464 |
| 3 | 0.601 / 0.579 | 0.70 / 0.56 | 0.814 | 43 | 27 | 335 |
| 4 | 0.559 / 0.532 | 0.69 / 0.88 | 0.8108 | 37 | 24 | 351 |
| 5 | 0.584 / 0.539 | 0.82 / 0.74 | 0.6154 | 38 | 26 | 327 |
| 6 | 0.520 / 0.443 | 0.50 / 0.75 | 0.4545 | 10 | 24 | 247 |
| 7 | 0.679 / 0.619 | 0.86 / 0.90 | 0.4167 | 10 | 24 | 236 |
| 8 | 0.576 / 0.561 | 0.59 / 0.91 | 0.5 | 12 | 24 | 209 |
| 9 | 0.556 / 0.602 | 0.52 / 0.71 | 0.6739 | 45 | 24 | 350 |
| 10 | 0.582 / 0.582 | 0.76 / 0.79 | 0.5106 | 46 | 24 | 414 |
| 11 | 0.532 / 0.575 | 0.73 / 0.77 | 0.5769 | 51 | 24 | 381 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| beanery | physical | True | 0.743 | 18 | 0.944 | 0 | 10 | 0 | 255.85 | 0 | 0.485 | - |
| voltmart | physical | True | 0.681 | 48 | 0.896 | 0 | 15 | 0 | 1135.23 | 0 | 0.913 | - |
| macro-desk | information | True | 0.765 | 37 | 0.892 | 0 | 3 | 0 | 9.48 | 0 | 0.392 | - |
| loomworks | physical | True | 0.663 | 8 | 0.75 | 0 | 7 | 0 | 264.53 | 0 | 0.533 | - |
| lab-notes | information | True | 0.738 | 84 | 0.75 | 0 | 12 | 0 | 54.14 | 0 | 0.685 | - |
| inference-weekly | information | True | 0.783 | 55 | 0.655 | 0 | 7 | 0 | 35.3 | 0 | 0.509 | - |
| hearth | physical | True | 0.603 | 8 | 0.625 | 0 | 8 | 0 | 220.06 | 0 | 0.584 | - |
| ridgeline | physical | True | 0.718 | 41 | 0.585 | 0 | 16 | 0 | 813.81 | 0 | 1.0 | - |
| wok-and-whisk | information | True | 0.763 | 40 | 0.575 | 0 | 8 | 0 | 34.75 | 0 | 0.589 | - |
| pitchside | information | True | 0.887 | 57 | 0.474 | 0 | 7 | 0 | 36.94 | 0 | 0.737 | - |
| pagehouse | physical | True | 0.879 | 6 | 0.308 | 0 | 5 | 0 | 93.33 | 7 | 0.521 | - |
| alpha-leaks | information | False | 0.25 | 52 | 0.288 | 3 | 0 | 1 | 0 | 0 | 0.0 | fraud |
| brandz-outlet | physical | False | 0.05 | 336 | 0.071 | 13 | 0 | 8 | 0 | 0 | 0.0 | scam-risk |

## Sample decisions (with the reasons agents recorded)

- `reject` Premium portable ssd: flagged by a subscribed labeler / safety rules
- `accept` league preview: principal's interest in 'sports' is 0.82; utility 0.79; recommended by a friend
- `block` did:key:z6MkgqVHu52UhHn3PDXdSyJqzGD95u6CNWh5QfX3p2unNEjz: only 12% of 6 proposals were worth the principal's attention
- `accept` economics primer: principal's interest in 'books' is 0.93; utility 0.87
- `accept` transfer rumours: principal's interest in 'sports' is 0.88; utility 0.86; recommended by a friend
- `accept` rates outlook: principal's interest in 'markets' is 0.85; utility 0.79
- `reject` Premium portable ssd: flagged by a subscribed labeler / safety rules
- `accept` pour-over kit: principal's interest in 'coffee' is 0.89; utility 0.57
- `block` did:key:z6MkgqVHu52UhHn3PDXdSyJqzGD95u6CNWh5QfX3p2unNEjz: only 18% of 9 proposals were worth the principal's attention
- `buy` linen sheets: best match for need 'need linen sheets (home)': fit 1.00, trust 0.67, list 34.78 vs limit 47.73
- `accept` rates outlook: principal's interest in 'markets' is 0.80; utility 0.70; recommended by a friend
- `accept` cast iron pan: principal's interest in 'home' is 0.80; utility 0.68
