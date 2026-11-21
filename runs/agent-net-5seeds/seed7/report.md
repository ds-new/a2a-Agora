# Agora agent-network simulation report

43 agents, 12 rounds, transport `memory`, seed 7.

## Totals

| metric | value |
|---|---|
| gmv | 2863.75 |
| deals_completed | 87 |
| deals_refunded | 11 |
| platform_fee | 0.0 |
| escrow_fees | 14.32 |
| referral_payouts | 2.56 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 127 |
| needs_created | 65 |
| a2a_messages | 4726 |
| intents | 0 |
| forwards | 197 |
| blocks | 25 |
| subscriptions | 77 |
| honest_proposals | 428 |
| honest_acceptance | 0.8037 |
| reputation_vs_quality_spearman | 0.356 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5222 | 0.6229 | 0.0219 | 2.54 | 1.0 | 0.0 | 4.33 | 31.35 |
| base skills only | 12 | 0.4794 | 0.5992 | 0.0778 | 1.78 | 0.808 | 0.0 | 2.92 | 19.09 |

Rejection reasons the agents sent back: with X skills: {'too-expensive': 13, 'attention-budget': 29, 'off-topic': 11, 'unsafe': 94}; base skills only: {'off-topic': 9, 'disliked-category': 8, 'too-expensive': 5, 'attention-budget': 2, 'unsafe': 28, 'not-shippable': 5}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.892 after learning vs 0.905 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 1.0 | 46.1 |
| subscribers | 8 | 0.85 | 21.8 |
| private | 3 | 0.778 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.375 / 0.063 | 0.52 / 0.22 | 0.7333 | 15 | 21 | 903 |
| 1 | 0.538 / 0.530 | 0.67 / 0.70 | 0.7895 | 57 | 39 | 428 |
| 2 | 0.532 / 0.419 | 0.58 / 0.52 | 0.8235 | 51 | 50 | 504 |
| 3 | 0.561 / 0.492 | 0.61 / 0.62 | 0.8919 | 37 | 28 | 333 |
| 4 | 0.575 / 0.516 | 0.66 / 0.48 | 0.8085 | 47 | 30 | 385 |
| 5 | 0.525 / 0.430 | 0.60 / 0.57 | 0.7778 | 45 | 24 | 346 |
| 6 | 0.423 / 0.455 | 0.53 / 0.63 | 0.9 | 10 | 24 | 300 |
| 7 | 0.439 / 0.521 | 0.36 / 0.60 | 0.8571 | 7 | 24 | 191 |
| 8 | 0.502 / 0.417 | 0.50 / 0.50 | 0.5556 | 9 | 24 | 186 |
| 9 | 0.518 / 0.498 | 0.66 / 0.55 | 0.7556 | 45 | 24 | 318 |
| 10 | 0.511 / 0.511 | 0.71 / 0.72 | 0.78 | 50 | 24 | 440 |
| 11 | 0.576 / 0.570 | 0.68 / 0.68 | 0.8545 | 55 | 24 | 392 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pagehouse | physical | True | 0.696 | 44 | 0.864 | 0 | 20 | 0 | 428.09 | 0 | 0.888 | - |
| macro-desk | information | True | 0.783 | 48 | 0.854 | 0 | 5 | 0 | 27.97 | 0 | 0.424 | - |
| lab-notes | information | True | 0.798 | 45 | 0.844 | 0 | 0 | 0 | 0 | 0 | 0.143 | - |
| loomworks | physical | True | 0.783 | 29 | 0.828 | 0 | 11 | 0 | 437.86 | 0 | 0.659 | - |
| ridgeline | physical | True | 0.881 | 34 | 0.824 | 0 | 16 | 0 | 743.83 | 0 | 1.0 | - |
| hearth | physical | True | 0.569 | 10 | 0.8 | 0 | 6 | 0 | 176.89 | 0 | 0.487 | - |
| pitchside | information | True | 0.736 | 38 | 0.789 | 0 | 1 | 0 | 4.81 | 0 | 0.417 | - |
| voltmart | physical | True | 0.584 | 41 | 0.78 | 0 | 11 | 0 | 906.21 | 0 | 0.704 | - |
| inference-weekly | information | True | 0.778 | 48 | 0.771 | 0 | 10 | 0 | 30.22 | 0 | 0.603 | - |
| wok-and-whisk | information | True | 0.583 | 81 | 0.753 | 0 | 4 | 0 | 21.66 | 0 | 0.634 | - |
| beanery | physical | True | 0.708 | 10 | 0.7 | 0 | 3 | 0 | 69.33 | 0 | 0.283 | - |
| alpha-leaks | information | False | 0.25 | 51 | 0.235 | 3 | 0 | 3 | 0 | 0 | 0.0 | fraud, scam-risk |
| brandz-outlet | physical | False | 0.05 | 336 | 0.054 | 19 | 0 | 8 | 0 | 0 | 0.0 | scam-risk |

## Sample decisions (with the reasons agents recorded)

- `accept` transfer rumours: exploring 'sports', which the principal never rated (picked by x_rank)
- `accept` night train guide: principal's interest in 'travel' is 0.69; utility 0.67; recommended by a friend
- `accept` wool socks: principal's interest in 'apparel' is 0.53; utility 0.48
- `reject` desk lamp: does not ship to the principal
- `reject` ceramic mug set: does not ship to the principal
- `accept` rail pass hacks: principal's interest in 'travel' is 0.69; utility 0.65
- `accept` wool socks: principal's interest in 'apparel' is 0.73; utility 0.66; x_rank position 2
- `accept` notes on LLM inference costs: principal's interest in 'ai' is 0.80; utility 0.74; x_rank position 3
- `reject` GPU market weekly: relevant, but attention for this tick is used up
- `accept` sci-fi novel: principal's interest in 'books' is 0.77; utility 0.55
- `accept` economics primer: principal's interest in 'books' is 0.80; utility 0.60
- `accept` merino t-shirt: exploring 'apparel', which the principal never rated
