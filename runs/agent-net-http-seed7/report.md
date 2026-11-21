# Agora agent-network simulation report

43 agents, 12 rounds, transport `http`, seed 7.

## Totals

| metric | value |
|---|---|
| gmv | 3367.41 |
| deals_completed | 97 |
| deals_refunded | 9 |
| platform_fee | 0.0 |
| escrow_fees | 16.82 |
| referral_payouts | 13.12 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 133 |
| needs_created | 75 |
| a2a_messages | 5035 |
| intents | 0 |
| forwards | 222 |
| blocks | 21 |
| subscriptions | 89 |
| honest_proposals | 485 |
| honest_acceptance | 0.7536 |
| reputation_vs_quality_spearman | 0.447 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5196 | 0.6443 | 0.0309 | 2.69 | 0.917 | 0.0 | 4.42 | 32.96 |
| base skills only | 12 | 0.4525 | 0.5632 | 0.0728 | 1.81 | 0.808 | 0.0 | 3.67 | 25.78 |

Rejection reasons the agents sent back: with X skills: {'off-topic': 16, 'too-expensive': 17, 'attention-budget': 38, 'disliked-category': 2, 'unsafe': 109}; base skills only: {'off-topic': 8, 'disliked-category': 2, 'too-expensive': 2, 'unsafe': 35, 'not-shippable': 6, 'attention-budget': 1}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.872 after learning vs 0.905 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 0.912 | 49.7 |
| subscribers | 8 | 0.8 | 24.9 |
| private | 3 | 0.875 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.384 / 0.158 | 0.55 / 0.36 | 0.7857 | 14 | 30 | 961 |
| 1 | 0.510 / 0.471 | 0.68 / 0.67 | 0.7037 | 54 | 34 | 432 |
| 2 | 0.495 / 0.453 | 0.52 / 0.67 | 0.7736 | 53 | 31 | 529 |
| 3 | 0.570 / 0.605 | 0.64 / 0.62 | 0.7755 | 49 | 43 | 434 |
| 4 | 0.598 / 0.503 | 0.79 / 0.71 | 0.8049 | 41 | 30 | 360 |
| 5 | 0.596 / 0.398 | 0.69 / 0.67 | 0.7857 | 42 | 24 | 389 |
| 6 | 0.471 / 0.470 | 0.67 / 0.60 | 0.6842 | 19 | 24 | 325 |
| 7 | 0.398 / 0.410 | 0.40 / 0.43 | 0.625 | 16 | 24 | 281 |
| 8 | 0.504 / 0.433 | 0.75 / 0.64 | 0.7826 | 23 | 24 | 248 |
| 9 | 0.571 / 0.483 | 0.67 / 0.43 | 0.7069 | 58 | 24 | 314 |
| 10 | 0.525 / 0.450 | 0.66 / 0.39 | 0.8 | 59 | 24 | 398 |
| 11 | 0.494 / 0.444 | 0.61 / 0.56 | 0.7414 | 57 | 24 | 364 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| beanery | physical | True | 0.708 | 16 | 0.875 | 0 | 6 | 0 | 152.73 | 0 | 0.334 | - |
| pagehouse | physical | True | 0.696 | 42 | 0.833 | 0 | 18 | 0 | 376.59 | 0 | 0.904 | - |
| voltmart | physical | True | 0.584 | 49 | 0.816 | 0 | 15 | 0 | 1217.51 | 0 | 0.961 | - |
| ridgeline | physical | True | 0.881 | 45 | 0.8 | 0 | 19 | 0 | 943.69 | 0 | 1.0 | - |
| macro-desk | information | True | 0.783 | 54 | 0.778 | 0 | 4 | 0 | 19.26 | 0 | 0.509 | - |
| pitchside | information | True | 0.736 | 37 | 0.73 | 0 | 6 | 0 | 26.2 | 0 | 0.575 | - |
| lab-notes | information | True | 0.798 | 55 | 0.727 | 0 | 3 | 0 | 16.26 | 0 | 0.496 | - |
| wok-and-whisk | information | True | 0.583 | 79 | 0.722 | 0 | 3 | 0 | 17.0 | 0 | 0.491 | - |
| loomworks | physical | True | 0.783 | 44 | 0.705 | 0 | 11 | 0 | 401.69 | 0 | 0.792 | - |
| inference-weekly | information | True | 0.778 | 55 | 0.691 | 0 | 6 | 0 | 17.34 | 0 | 0.448 | - |
| hearth | physical | True | 0.569 | 9 | 0.636 | 0 | 6 | 0 | 149.2 | 2 | 0.607 | - |
| alpha-leaks | information | False | 0.25 | 66 | 0.303 | 1 | 0 | 1 | 0 | 0 | 0.0 | fraud |
| brandz-outlet | physical | False | 0.05 | 336 | 0.042 | 15 | 0 | 8 | 0 | 0 | 0.0 | scam-risk |

## Sample decisions (with the reasons agents recorded)

- `reject` [report] Kyoto on a budget: above the principal's price ceiling
- `reject` [report] Patagonia trek log: above the principal's price ceiling
- `reject` [report] Patagonia trek log: above the principal's price ceiling
- `accept` portable ssd: principal's interest in 'electronics' is 0.77; utility 0.58
- `accept` [report] Patagonia trek log: principal's interest in 'travel' is 0.93; utility 0.90; recommended by a friend
- `accept` Patagonia trek log: principal's interest in 'travel' is 0.93; utility 0.85
- `accept` agent protocol deep dive: principal's interest in 'ai' is 0.79; utility 0.69; x_rank position 1
- `accept` wireless earbuds: principal's interest in 'electronics' is 0.77; utility 0.66; x_rank position 2
- `accept` night train guide: exploring 'travel', which the principal never rated (picked by x_rank)
- `accept` knife skills guide: principal's interest in 'cooking' is 0.80; utility 0.67
- `accept` history of computing: principal's interest in 'books' is 0.71; utility 0.52
- `accept` running shorts: exploring 'apparel', which the principal never rated
