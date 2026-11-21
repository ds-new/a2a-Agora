# Agora agent-network simulation report

43 agents, 12 rounds, transport `memory`, seed 8.

## Totals

| metric | value |
|---|---|
| gmv | 3432.36 |
| deals_completed | 120 |
| deals_refunded | 9 |
| platform_fee | 0.0 |
| escrow_fees | 17.23 |
| referral_payouts | 20.51 |
| paid_out_to_bad_actors | 0 |
| money_conserved | True |
| offers_published | 123 |
| needs_created | 78 |
| a2a_messages | 5222 |
| intents | 2 |
| forwards | 476 |
| blocks | 23 |
| subscriptions | 80 |
| honest_proposals | 402 |
| honest_acceptance | 0.6741 |
| reputation_vs_quality_spearman | 0.796 |

## Consumer agents: with vs without X's ranking stack as skills

| group | consumers | relevance of shown | liked | scam share | shown/tick | need fulfilment | hours to fulfil | purchases/consumer | surplus/consumer |
|---|---|---|---|---|---|---|---|---|---|
| with X skills | 12 | 0.5556 | 0.6894 | 0.0327 | 2.55 | 0.931 | 0.0 | 5.5 | 63.9 |
| base skills only | 12 | 0.5238 | 0.5803 | 0.071 | 2.25 | 0.781 | 0.0 | 4.5 | 36.0 |

Rejection reasons the agents sent back: with X skills: {'disliked-category': 7, 'off-topic': 19, 'attention-budget': 34, 'unsafe': 83, 'too-expensive': 12}; base skills only: {'off-topic': 16, 'not-shippable': 8, 'disliked-category': 3, 'attention-budget': 4, 'unsafe': 44, 'too-expensive': 3, 'blocked': 3}

## Preference learning

Spearman correlation between the principal's true tastes over 12 categories and the agent's profile: 0.906 after learning vs 0.903 from stated preferences alone.

## Disclosure

| disclosure | consumers | need fulfilment | proposals received/consumer |
|---|---|---|---|
| public | 13 | 0.893 | 44.1 |
| subscribers | 8 | 0.875 | 23.9 |
| private | 3 | 0.667 | 14.0 |

## By round

| round | relevance X / base | liked X / base | honest producer acceptance | honest proposals | spam proposals | A2A messages |
|---|---|---|---|---|---|---|
| 0 | 0.422 / 0.288 | 0.62 / 0.38 | 1.0 | 13 | 42 | 1034 |
| 1 | 0.580 / 0.480 | 0.59 / 0.47 | 0.8125 | 48 | 38 | 518 |
| 2 | 0.529 / 0.598 | 0.82 / 0.62 | 0.5957 | 47 | 40 | 557 |
| 3 | 0.501 / 0.392 | 0.62 / 0.48 | 0.675 | 40 | 24 | 425 |
| 4 | 0.494 / 0.557 | 0.70 / 0.44 | 0.7273 | 44 | 24 | 422 |
| 5 | 0.591 / 0.597 | 0.76 / 0.76 | 0.675 | 40 | 24 | 333 |
| 6 | 0.659 / 0.585 | 0.73 / 0.42 | 0.8 | 10 | 24 | 231 |
| 7 | 0.610 / 0.502 | 0.85 / 0.74 | 0.5455 | 12 | 24 | 248 |
| 8 | 0.552 / 0.532 | 0.75 / 0.68 | 0.75 | 4 | 24 | 242 |
| 9 | 0.630 / 0.606 | 0.70 / 0.70 | 0.6596 | 47 | 24 | 355 |
| 10 | 0.606 / 0.577 | 0.74 / 0.74 | 0.617 | 47 | 24 | 432 |
| 11 | 0.584 / 0.562 | 0.57 / 0.52 | 0.549 | 50 | 24 | 425 |

## Producers

| producer | kind | honest | quality | proposals | acceptance | blocked by | sales | refunds | revenue | made to order | reputation | labels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pitchside | information | True | 0.664 | 9 | 1.0 | 0 | 6 | 0 | 30.27 | 0 | 0.292 | - |
| pagehouse | physical | True | 0.634 | 4 | 0.8 | 0 | 5 | 0 | 87.5 | 1 | 0.484 | - |
| macro-desk | information | True | 0.793 | 51 | 0.765 | 0 | 2 | 0 | 9.04 | 0 | 0.505 | - |
| hearth | physical | True | 0.882 | 82 | 0.728 | 0 | 36 | 0 | 956.83 | 0 | 1.0 | - |
| ridgeline | physical | True | 0.854 | 11 | 0.727 | 0 | 13 | 0 | 643.7 | 0 | 0.72 | - |
| wok-and-whisk | information | True | 0.763 | 45 | 0.711 | 0 | 6 | 0 | 19.91 | 0 | 0.42 | - |
| voltmart | physical | True | 0.748 | 30 | 0.7 | 0 | 15 | 0 | 1226.99 | 0 | 0.818 | - |
| inference-weekly | information | True | 0.749 | 80 | 0.625 | 0 | 13 | 0 | 50.18 | 0 | 0.581 | - |
| lab-notes | information | True | 0.928 | 81 | 0.568 | 0 | 15 | 0 | 72.63 | 0 | 0.638 | - |
| alpha-leaks | information | False | 0.25 | 68 | 0.485 | 3 | 0 | 5 | 0 | 0 | 0.0 | fraud, scam-risk |
| beanery | physical | True | 0.601 | 8 | 0.375 | 0 | 3 | 0 | 66.83 | 0 | 0.211 | - |
| brandz-outlet | physical | False | 0.05 | 336 | 0.057 | 14 | 0 | 4 | 0 | 0 | 0.0 | scam-risk |
| loomworks | physical | True | 0.84 | 1 | 0.0 | 0 | 6 | 0 | 230.74 | 0 | 0.486 | - |

## Sample decisions (with the reasons agents recorded)

- `reject` Premium portable ssd: flagged by a subscribed labeler / safety rules
- `accept` weeknight noodle recipes: exploring 'cooking', which the principal never rated (picked by x_rank)
- `block` did:key:z6MkgqVHu52UhHn3PDXdSyJqzGD95u6CNWh5QfX3p2unNEjz: only 18% of 9 proposals were worth the principal's attention
- `accept` knife skills guide: principal's interest in 'cooking' is 0.78; utility 0.77; recommended by a friend
- `accept` cold brew concentrate: principal's interest in 'coffee' is 0.91; utility 0.76; recommended by a friend
- `accept` usb-c hub: exploring 'electronics', which the principal never rated
- `accept` sourdough troubleshooting: principal's interest in 'cooking' is 0.76; utility 0.68
- `accept` RL fine-tuning tricks: principal's interest in 'ai' is 0.68; utility 0.63
- `block` did:key:z6MkgqVHu52UhHn3PDXdSyJqzGD95u6CNWh5QfX3p2unNEjz: only 18% of 9 proposals were worth the principal's attention
- `reject` Premium portable ssd: flagged by a subscribed labeler / safety rules
- `accept` usb-c hub: principal's interest in 'electronics' is 0.88; utility 0.79; recommended by a friend
- `reject` [report] rates outlook: above the principal's price ceiling
