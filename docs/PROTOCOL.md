# Agora 协议参考（v0.2）

## 1. A2A v1.0 绑定

依据 [a2aproject/A2A](https://github.com/a2aproject/A2A) @ `5f931b8` 的 `specification/a2a.proto` 和 `docs/specification.md`。

| 项目 | 实现 |
|---|---|
| Agent Card | `GET /.well-known/agent-card.json`；`supportedInterfaces=[{url, protocolBinding:"JSONRPC", protocolVersion:"1.0"}]`；签名用 detached JWS（EdDSA，`kid`=did:key）加 RFC 8785 |
| 端点 | `POST /a2a`，JSON-RPC 2.0 |
| 方法 | `SendMessage` `SendStreamingMessage`(SSE) `GetTask` `ListTasks` `CancelTask` `SubscribeToTask`(SSE) `GetExtendedAgentCard`(→ -32007) 推送配置四个方法(→ -32003) |
| 服务参数 | 请求头 `A2A-Version: 1.0`（缺省按 0.3 处理，返回 -32009）；`A2A-Extensions` 为逗号分隔的 URI；声明为 required 但请求未带的扩展返回 -32008 |
| 数据模型 | ProtoJSON camelCase；`TASK_STATE_*`、`ROLE_*` 枚举；Part 必须且只能包含 `text`/`raw`/`url`/`data` 之一；`SendMessageResponse` 为 `{"task"}` 或 `{"message"}`；流事件为 `task`/`message`/`statusUpdate`/`artifactUpdate` |
| 错误码 | -32001 TaskNotFound、-32002 TaskNotCancelable、-32003 PushNotificationNotSupported、-32004 UnsupportedOperation、-32005 ContentTypeNotSupported、-32006 InvalidAgentResponse、-32007 ExtendedAgentCardNotConfigured、-32008 ExtensionSupportRequired、-32009 VersionNotSupported |
| 未实现 | gRPC 和 HTTP+JSON 绑定、推送通知、多租户（`tenant`）、`securitySchemes` |

扩展 URI（Agent Card 的 `capabilities.extensions`）：

- `urn:agora:ext:market:v1`：Offer、背书、求购、议价、履约。`params = {"did", "roles"}`
- `urn:agora:ext:ap2-mandates:v0.2`：AP2 v0.2 授权链，JWS 形式
- `urn:agora:ext:gossip:v1`：对等节点与签名对象交换
- `urn:agora:ext:agent-network:v1`：兴趣卡、提议、签名反馈、查询、朋友转发（v0.2 新增）

每条消息的第一个 `data` part 必须带 `type`，可以再附一个 `text` part 写给人或大模型看。

**传输层不承担身份认证。** 会影响接收方如何评价发送方的请求（提议、转发、查询、加好友、订阅），以及所有涉及钱的请求，都在请求体里带签名指令（第 4 节），接收方据此确认是谁发的、是不是发给自己的。

## 2. 消息类型

### 2.1 智能体网络（v0.2 新增或改动）

| type | 发给 | 主要字段 | 返回 |
|---|---|---|---|
| `agora.interest.share` | 生产者 / 朋友 | `card`：签名兴趣卡 | `agora.ack {accepted}`；只接受比已存卡片更新的 `issuedAt` |
| `agora.follow` | 生产者 | `instruction`：签名的 `{type:"agora.follow", target, rpcUrl}`；`card?` | `agora.follow.ok` |
| `agora.friend` | 消费者 | `instruction`：签名的 `{type:"agora.friend", target, rpcUrl}` | `agora.friend.ok` |
| `agora.proposal` | 消费者 | `offer`；`proposal`：签名的 `{type:"agora.proposal", target, offerId, pitch, intentId?}`，必须由 Offer 的生产者签名 | `agora.proposal.ack {queued}`；收件即拒时另带 `feedback`（签名反馈）；伪造、发错对象或重放时返回 `agora.error` |
| `agora.proposal.response` | 生产者 | `feedback[]`：签名反馈，按生产者批量回传 | `agora.ack` |
| `agora.query` | 生产者 / 朋友 | `query`：签名的 `{type:"agora.query", target, need{id,text,kind,category,maxPrice,attempts}, region?}` | `agora.query.reply {items[]}`：生产者回 `{offer, pitch}`（可现场生产），朋友回 `{endorsement}`；非朋友得到空列表 |
| `agora.recommend` | 朋友 | `endorsement`；`recommend`：签名的 `{type:"agora.recommend", target, endorsementId, note}`，必须由背书链最末端的转发者签名 | `agora.ack {accepted}` |
| `agora.intent.push` | 订阅的生产者 | `intent`：签名求购 | `agora.ack`；能供货的生产者随后发 `agora.proposal`（带 `intentId`） |

v0.1 的 `agora.offer.push` 和 `agora.endorsement.push`（推给所有关注者）已移除，由定向的 `agora.proposal` 和 `agora.recommend` 取代。

### 2.2 发现与交易（与 v0.1 相同）

| type | 发给 | 主要字段 | 返回 |
|---|---|---|---|
| `agora.hello` | 任意 | `base` | `agora.hello.reply` |
| `agora.gossip` | 任意 | `from`, `peers[]`, `objects[]`（签名令牌） | `agora.gossip.reply`（同结构） |
| `agora.feed` | 生产者 | — | `agora.feed {offers[]}` |
| `agora.rfq` | 生产者 | `offer`, `quantity`, `region`, `buyer`, `escrows[]`, `endorsement?` | Task `INPUT_REQUIRED` + `agora.quote {checkout, unitPrice, round, final, accepted, listPrice}`；不接单则为 `REJECTED`；免费信息直接拒绝（内容已在 Offer 里） |
| `agora.counter` | 同一任务 | `price` | `INPUT_REQUIRED` + 新的 `agora.quote` |
| `agora.walk` | 同一任务 | — | `REJECTED` |
| `agora.accept` | 同一任务 | `checkoutMandate`, `openCheckoutMandate` | `INPUT_REQUIRED` + `agora.awaiting_funding {escrow, escrowUrl, checkout, amount}` |
| `agora.funded` | 同一任务 | `escrowId` | `COMPLETED` + artifact `agora.fulfilment {kind, delivery 或 content}` |
| `agora.escrow.open` | 托管 | `checkout` | `agora.escrow.opened {escrowId, payTo, amount, currency}` |
| `agora.escrow.fund` | 托管 | `escrowId`, `receipt` | `agora.escrow.funded` |
| `agora.escrow.status` | 托管 | `escrowId` | `agora.escrow.status {status, checkoutHash, amount}` |
| `agora.escrow.release` | 托管 | `instruction`：签名的 `agora.release {escrowId}` | `agora.settlement {settlement}` |
| `agora.escrow.dispute` | 托管 | `instruction`：签名的 `agora.dispute {escrowId}`，`evidence` | `agora.settlement` 或 `agora.dispute.rejected` |
| `agora.pay` | 银行 | `openPaymentMandate`, `paymentMandate`, `reference` | `agora.payment.receipt {receipt}` |
| `agora.transfer` | 银行 | `orders[]`：签名的 `agora.transfer-order {to, amount, currency, reference}` | `agora.transfer.receipts` |
| `agora.balance` | 银行 | `instruction`：签名的 `{type:"agora.balance"}`，只返回签名者自己的余额 | `agora.balance {did, balance}` |
| `agora.ship` | 物流 | `order`：签名的 `agora.ship-order {checkout}` | `agora.delivery {delivery}` |
| `agora.return` | 物流 | `order`：签名的 `agora.return-order {checkout}` | `agora.delivery`（status=returned） |
| `agora.labels.query` | 标注方 | `subject` | `agora.labels {labels[]}` |

请求无效时（签名错误、越权、库存不足等）：如果已有任务，任务转为 `REJECTED`，状态消息里附 `agora.error`；没有任务就直接回复 `agora.error` 消息。JSON-RPC 层面的错误使用上表中的标准错误码。

## 3. 签名对象

全部是紧凑 JWS（`alg=EdDSA`，`kid`=签名者 did:key，`typ` 见下表）。`*Id` 等于去掉该字段后 payload 的 `sha256:` + JCS 哈希。

| typ | 签名者字段 | 主要字段 |
|---|---|---|
| `agora.offer+jws` | `producer` | `offerId`, `kind`(physical/information), `title`, `description`, `category`, `tags`, `price{amount,currency}`, `referral{bps,maxDepth}`, `createdAt`, `expiresAt`；实体另有 `inventory`, `shipping{regions,days}`；信息另有 `license`，免费带 `content`，付费带 `contentHash` 和 `teaser` |
| `agora.endorsement+jws` | `endorser` | `endorsementId`, `offerId`, 根节点带 `offer`(令牌)，非根节点带 `parent`(上级背书令牌), `comment?` |
| `agora.intent+jws` | `consumer` | `intentId`, `consumerUrl`, `text`, `kind`, `category`, `maxPrice`, `quantity`, `region`, `expiresAt` |
| `agora.interest+jws` | `agent` | `cardId`, `agentUrl`, `kinds[]`, `categories{品类: 权重}`, `avoid[]`, `priceMax{品类: 价格}`, `maxPerDay`, `region`, `disclosure`, `issuedAt`, `expiresAt`（默认 72 小时） |
| `agora.feedback+jws` | `from` | `to`(被评价的生产者), `offerId`, `decision`(accept/reject/purchased), `reasons[]`（理由码，见第 5 节）, `at`；接收方核对 `to` 是自己，按令牌哈希去重 |
| `agora.checkout+jws` | `merchant` | `checkoutId`, `buyer`, `lineItems[]`, `shipping`, `total`, `escrow`, `referral{bps,chain[]}`, `contentHash`, `round`, `iat`, `exp` |
| `agora.payment-receipt+jws` | `bank` | `transactionId`, `payer`, `payee`, `amount`, `reference` |
| `agora.delivery+jws` | `carrier` | `shipmentId`, `checkoutHash`, `merchant`, `buyer`, `status`(delivered/returned) |
| `agora.content+jws` | `producer` | `offerId`, `buyer`, `content`, `contentHash` |
| `agora.settlement+jws` | `escrow` | `escrowId`, `checkout`(令牌), `checkoutHash`, `merchant`, `buyer`, `amount`, `status`(released/refunded), `reason`, `splits[]`, `escrowFee` |
| `agora.review+jws` | `reviewer` | `reviewId`, `settlement`(令牌，且必须以评价者为买家), `subject`, `rating` 1–5 |
| `agora.label+jws` | `labeler` | `labelId`, `subject`, `subjectType`, `label`(fraud/scam-risk/hash-mismatch/…), `severity`, `evidence[]`, `exp` |
| `agora.instruction+jws` | `by` | `type`，`nonce`，`at`，以及各自的字段；见第 4 节 |
| `ap2.mandate+jws` | `iss` | 见第 7 节 |

## 4. 签名指令

`agora.instruction+jws` 统一承载「某人要求做某事」：

| `type` | 签名者 | 字段 | 接收方检查 |
|---|---|---|---|
| `agora.proposal` | 生产者 | `target`, `offerId`, `pitch`, `intentId?` | 签名者 = Offer 的生产者；`target` = 自己；`offerId` 一致；nonce 未用过 |
| `agora.recommend` | 转发者 | `target`, `endorsementId`, `note` | 签名者 = 背书链末端；`target` = 自己；`endorsementId` 一致；nonce 未用过；签名者是朋友 |
| `agora.query` | 提问者 | `target`, `need`, `region?` | `target` = 自己；nonce 未用过；朋友端只回答朋友 |
| `agora.friend` | 消费者 | `target`, `rpcUrl` | `target` = 自己；nonce 未用过 |
| `agora.follow` | 消费者 | `target`, `rpcUrl` | `target` = 自己 |
| `agora.balance` | 账户持有人 | — | 只返回签名者自己的余额 |
| `agora.release` / `agora.dispute` | 买家 | `escrowId` | 签名者是该托管的买家 |
| `agora.ship-order` / `agora.return-order` | 商家 / 买家 | `checkout` | 发货单须由报价单上的商家签名，退货单须由买家签名 |
| `agora.transfer-order` | 托管方 | `to`, `amount`, `currency`, `reference` | 签名者即付款方；nonce 未用过；余额充足 |

所有指令都带 `at`，超过 3600 秒的一律拒绝；需要防重放的指令由接收方记住用过的 `nonce`。

## 5. 理由码与披露级别

签名反馈里的理由码（`REASONS`）：

| 理由码 | 含义 | 何时给出 |
|---|---|---|
| `need-match` | 符合一个当前需求 | 为需求购买时 |
| `relevant` | 符合用户兴趣 | 放行展示时 |
| `off-topic` | 与用户兴趣不符 | 决策时 |
| `disliked-category` | 用户说过不要这个品类 | 决策时（硬性） |
| `too-expensive` | 超过用户的价格上限 | 决策时 |
| `low-trust` | 生产者的已验证记录太差 | 决策时（硬性） |
| `unsafe` | 订阅的标注方或安全规则判为不安全 | 决策时（硬性） |
| `attention-budget` | 相关，但本轮注意力额度已用完 | 决策时 |
| `not-shippable` | 不发货到用户地区 | 决策时（硬性） |
| `duplicate` | 已经决定过 | 收件时 |
| `rate-limit` | 超过兴趣卡上声明的每日上限 | 收件时 |
| `blocked` | 生产者已被屏蔽 | 收件时 |
| `unsolicited` | 用户选择私密披露，未订阅且不是求购响应 | 收件时 |

披露级别（`DISCLOSURE`）：

| 级别 | 卡片内容 | 传播 |
|---|---|---|
| `public` | 前 4 个品类，权重粗化到 0.1 | 发给订阅的生产者和朋友，并经 gossip 扩散 |
| `subscribers` | 前 8 个品类，权重保留两位小数 | 只发给订阅的生产者和朋友；gossip 不转发 |
| `private` | 不发卡 | 只经求购表达需求；未订阅生产者的提议收件即拒（`unsolicited`） |

## 6. gossip

可经 gossip 交换的对象：Offer、背书、结算、评价、标签、求购，以及 `disclosure = public` 的兴趣卡。每个智能体按「对端 × 对象类型」记录水位，每次每类最多发 40 个对方没收到的对象；收到后逐个验签，按令牌哈希去重。

## 7. AP2 v0.2 授权链

依据 [google-agentic-commerce/AP2](https://github.com/google-agentic-commerce/AP2) @ `e1ea56d`，`docs/ap2/specification.md` 和 `code/sdk/schemas/ap2/*.json`。

| 授权 | `vct` | 签名者 | 字段 |
|---|---|---|---|
| 开放结账授权 | `mandate.checkout.open.1` | 用户 | `constraints`: `checkout.line_items{items[{kind?,category?,maxQuantity}]}`、`checkout.allowed_merchants?`；`cnf{kid: 智能体DID}` |
| 开放支付授权 | `mandate.payment.open.1` | 用户 | `constraints`: `payment.amount_range{min,max}`、`payment.budget{max}`、`payment.allowed_payees?`；`cnf`；`payment_instrument{holder}` |
| 封闭结账授权 | `mandate.checkout.1` | 智能体 | `checkout_jwt`(商家签名的报价单), `checkout_hash` |
| 封闭支付授权 | `mandate.payment.1` | 智能体 | `transaction_id`(=escrowId), `payee{did}`, `payment_amount`, `payment_instrument` |

这里对应 AP2 的「用户不在场（Human Not Present）」模式：校验方拿到的始终是封闭授权，加上用来授权该智能体公钥的开放授权。消费者智能体的开放支付授权只允许付给它信任的托管方。

与 AP2 的偏差：

1. 用紧凑 JWS 代替 SD-JWT VC，因此没有选择性披露。
2. `cnf` 用 `{kid: did}` 代替 JWK。
3. AP2 要求开放授权单次使用、被拒才能再出示；这里 `payment.budget` 改为按累计额度执行，由银行按开放授权 ID 记账。
4. 角色合并：银行同时担任 Credential Provider 和 Merchant Payment Processor；用户的私钥担任 Trusted Surface。
5. 扩展 URI 用 `urn:agora:ext:ap2-mandates:v0.2`，没有使用 AP2 官方 URI，因为第 1–3 点并不完全符合 AP2。
