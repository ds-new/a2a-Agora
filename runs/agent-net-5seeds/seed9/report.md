# Agora agent-network simulation report

43 agents, 12 rounds, transport `memory`, seed 9.

## Totals

| metric | value |
|---|---|
| gmv | 2169.88 |
| deals_completed | 84 |
| deals_refunded | 5 |
| platform_fee | 0.0 |
| escrow_fees | 10.82 |
| referral_payouts | 12.71 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 126 |
| needs_created | 73 |
| a2a_messages | 4648 |
| intents | 0 |
| forwards | 350 |
| blocks | 15 |
| subscriptions | 75 |
| honest_proposals | 382 |
| honest_acceptance | 0.7066 |
| reputation_vs_quality_spearman | 0.22 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5165 | 0.6393 | 0.0572 | 2.79 | 0.757 | 0.0 | 3.92 | 25.77 |
| base skills only | 12 | 0.5042 | 0.6014 | 0.0385 | 1.99 | 0.846 | 0.0 | 3.08 | 32.22 |

Rejection reasons the agents sent back: with X skills: {'off-topic': 56, 'disliked-category': 5, 'attention-budget': 23, 'unsafe': 97}; base skills only: {'off-topic': 6, 'disliked-category': 3, 'attention-budget': 6, 'unsafe': 33, 'not-shippable': 15, 'too-expensive': 2}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.873 after learning vs 0.881 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 0.737 | 38.8 |
| subscribers | 8 | 0.85 | 26.5 |
| private | 3 | 1.0 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.334 / 0.313 | 0.50 / 0.11 | 1.0 | 11 | 24 | 875 |
| 1 | 0.442 / 0.408 | 0.58 / 0.54 | 0.8049 | 41 | 56 | 507 |
| 2 | 0.595 / 0.482 | 0.74 / 0.61 | 0.8537 | 40 | 35 | 532 |
| 3 | 0.527 / 0.516 | 0.71 / 0.66 | 0.7273 | 33 | 29 | 343 |
| 4 | 0.544 / 0.602 | 0.67 / 0.82 | 0.6667 | 39 | 24 | 320 |
| 5 | 0.511 / 0.519 | 0.67 / 0.61 | 0.6512 | 43 | 24 | 317 |
| 6 | 0.424 / 0.566 | 0.47 / 0.57 | 0.7 | 10 | 24 | 241 |
| 7 | 0.487 / 0.369 | 0.57 / 0.50 | 0.8182 | 10 | 24 | 200 |
| 8 | 0.476 / 0.464 | 0.48 / 0.50 | 0.7143 | 13 | 24 | 267 |
| 9 | 0.573 / 0.527 | 0.63 / 0.68 | 0.6531 | 47 | 24 | 337 |
| 10 | 0.608 / 0.556 | 0.72 / 0.65 | 0.6383 | 45 | 24 | 392 |
| 11 | 0.537 / 0.576 | 0.71 / 0.65 | 0.6038 | 50 | 24 | 317 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| alpha-leaks | information | False | 0.25 | 41 | 0.902 | 0 | 0 | 0 | 0 | 0 | 0.168 | - |
| ridgeline | physical | True | 0.719 | 47 | 0.875 | 0 | 27 | 0 | 1340.67 | 0 | 1.0 | - |
| loomworks | physical | True | 0.753 | 6 | 0.833 | 0 | 1 | 0 | 35.03 | 0 | 0.175 | - |
| lab-notes | information | True | 0.908 | 61 | 0.803 | 0 | 5 | 0 | 32.12 | 0 | 0.536 | - |
| inference-weekly | information | True | 0.906 | 18 | 0.778 | 0 | 3 | 0 | 9.32 | 0 | 0.283 | - |
| pitchside | information | True | 0.844 | 82 | 0.707 | 0 | 12 | 0 | 31.29 | 0 | 0.643 | - |
| beanery | physical | True | 0.657 | 14 | 0.643 | 0 | 4 | 0 | 96.48 | 0 | 0.419 | - |
| wok-and-whisk | information | True | 0.682 | 64 | 0.641 | 0 | 11 | 0 | 32.17 | 0 | 0.564 | - |
| macro-desk | information | True | 0.874 | 72 | 0.625 | 0 | 11 | 0 | 41.41 | 0 | 0.706 | - |
| pagehouse | physical | True | 0.751 | 4 | 0.571 | 0 | 3 | 0 | 58.05 | 3 | 0.286 | - |
| voltmart | physical | True | 0.83 | 6 | 0.5 | 0 | 6 | 0 | 447.42 | 0 | 0.573 | - |
| hearth | physical | True | 0.905 | 8 | 0.5 | 0 | 1 | 0 | 22.39 | 6 | 0.107 | - |
| brandz-outlet | physical | False | 0.05 | 336 | 0.086 | 9 | 0 | 5 | 0 | 0 | 0.0 | scam-risk |

## Sample decisions (with the reasons agents recorded)

- `accept` rates outlook: principal's interest in 'markets' is 0.62; utility 0.59
- `accept` night train guide: free and matches need 'need a good read on Kyoto on a budget (travel)' (fit 0.68)
- `accept` earnings preview: principal's interest in 'markets' is 0.69; utility 0.65
- `accept` [report] training science: principal's interest in 'sports' is 0.84; utility 0.86; recommended by a friend
- `accept` [report] training science: principal's interest in 'sports' is 0.84; utility 0.80
- `accept` [report] Kyoto on a budget: exploring 'travel', which the principal never rated
- `reject` Premium usb-c hub: flagged by a subscribed labeler / safety rules
- `accept` earnings preview: free and matches need 'need a good read on earnings preview (markets)' (fit 0.99)
- `accept` knife skills guide: principal's interest in 'cooking' is 0.85; utility 0.84; recommended by a friend
- `accept` night train guide: principal's interest in 'travel' is 0.90; utility 0.86
- `accept` spice blending: principal's interest in 'cooking' is 0.74; utility 0.74; recommended by a friend
- `block` did:key:z6MkgqVHu52UhHn3PDXdSyJqzGD95u6CNWh5QfX3p2unNEjz: only 18% of 9 proposals were worth the principal's attention
