# M8-F162 Dry-Run Audit — Temporal `default` namespace hygiene

**Status: DRY RUN. Nothing was terminated, signalled, cancelled, or deleted.** This report
supersedes the cancelled M8-12 terminate-pass and is read-only end to end: every Temporal call
below is `list_workflows`, `count_workflows`, `list_namespaces`, or `get_workflow_handle` used
only for read purposes. No worker was started. Live Postgres (`jarvis`) was read with plain
`SELECT`s only.

Audited: 2026-07-27, worktree `D:\Projects\Jarvis-lanes\m8-12` (`lane/m8-12` @ `0386569`),
against `localhost:7233` namespace `default` and Postgres db `jarvis`.

---

## 1. Totals

| Metric | Count |
|---|---|
| Total workflow executions on `default` (all types, all states) | **478** |
| — of which `RUNNING` | 478 (100%) |
| — of which any other state (closed/terminated/etc.) | 0 |
| Workflow types present | 1 (`BusinessManager`) |
| Protected (live Manager) executions | **3** |
| **Orphan executions (would be terminated on approval)** | **475** |

`client.count_workflows("")` and the full `list_workflows("")` enumeration agree at 478; every
record's `status` is `RUNNING`. There are no closed executions to worry about double-counting
and no hidden second workflow type.

Note on the packet's original estimate: `docs/DECISIONS.md` (M8-F162) recorded "~445 orphaned"
at the time the finding was flagged. The live count is now 475 orphans (478 − 3), all with
`start_time` of **2026-07-27** — i.e. all of them post-date that finding (recorded against
commit `89a7bfc`, dated 2026-07-26) and the M8-12 packet commit (`0386569`) that flagged the
routing bug as urgent. The leak did not stop when the finding was recorded — see §6.

## 2 & 3. The orphan set, grouped, with evidence

**Classification method (three independent checks, all had to agree):**

1. **id-shape check (weak, ruled out as sole evidence):** every orphan id matches
   `bm-biz_<32-char lowercase hex>`, produced by `business_workflow_id()` wrapping
   `jarvis/kernel/ids.py::new_business_id()` (`f"biz_{uuid.uuid4().hex}"`). This is *identical*
   in shape to the three protected ids — uuid4 hex gives no way to tell a real business from a
   test one by looking at the id alone. This is exactly the packet's own escalation warning
   ("a protected id is ambiguous"), so shape was not used as evidence, only as the pattern used
   to group ids below.
2. **Cross-check against live `business_instances` (decisive):** `SELECT business_id,
   display_name, lifecycle_state FROM business_instances` on the live `jarvis` database returns
   **exactly 3 rows** (below, §4). Every one of the 475 orphan business ids is absent from that
   table — there is no registry row, of any lifecycle state, that any of them could belong to.
   A `BusinessManagerWorkflow` with no backing registry row is definitionally orphaned: nothing
   in the platform can ever approve, wake, or read a status for it again.
3. **Start-time correlation (corroborating):** the 3 protected executions started
   2026-07-26 09:53 / 12:29 / 21:52 UTC (matching `business_instances.created_at` for Trailhead,
   Summit, Portfolio Watch, §4). All 475 orphans started **2026-07-27**, clustered into 37
   distinct minute-buckets between 14:00 and 22:58 UTC, in batch sizes of 9, 11, 18, 20, 22, or
   29 — the signature of repeated packet/gate-suite live-verification runs through the day, not
   a single bulk script. This is temporally and volumetrically disjoint from the 3 real
   businesses and lines up with §6's root cause (every lane's live-verification work landing on
   `default` instead of its own namespace).

All 475 pass checks 2 and 3. **Every group below is orphaned for the same reason** (absent from
`business_instances`); they are grouped by `start_time` minute-bucket only for readability — id
shape does not distinguish sub-classes, so there is one evidentiary class, presented in 37
timestamped batches, every id present.

<details>
<summary><b>Full orphan list — 475 ids in 37 start-time groups (click to expand)</b></summary>

### Group 1: start_time 2026-07-27 14:00 UTC (9 workflows)
`bm-biz_05a61b7212fc441b90026e8566465528`, `bm-biz_5ad665a763ac46428251051dbc4d5567`,
`bm-biz_704b17dc6a744823ac7c22122dab1506`, `bm-biz_7190fd3f8bf0482c966189df9f8d971d`,
`bm-biz_84c31496e2524c1a872376481e3b6dd3`, `bm-biz_87edd51c51534e3ebb3d0f35bff6bcb9`,
`bm-biz_dcaaf7cf412b45f991fe31677f05cc0c`, `bm-biz_e065d4086be14e0bb5d8c5f6983aeaf1`,
`bm-biz_ef185c3a933f4d899017a25a22cd0144`

### Group 2: start_time 2026-07-27 14:06 UTC (9 workflows)
`bm-biz_0a4f871ca33e4e989c3abe2fea14420f`, `bm-biz_10eaf2127c6b49a284c62e84c50b82e9`,
`bm-biz_1f2df0475dc846b58d57e211fa993ec9`, `bm-biz_3c68b75de75d4b6594882d2d2a3a6cdb`,
`bm-biz_3d8a5fdd2a054890b72eafa753f6f513`, `bm-biz_3f20e893b9454d28ab364cca6e07330c`,
`bm-biz_5be2aa5760f64a3ca774c10b52604b1b`, `bm-biz_71fded1e3604471d9963ef2f8b54a9e0`,
`bm-biz_819f526780e34996b072c3960ccfde00`

### Group 3: start_time 2026-07-27 14:07 UTC (9 workflows)
`bm-biz_4c61226fa26847479ac59b36f46411b6`, `bm-biz_56a21ce9b1a64de4944033e11f1c0521`,
`bm-biz_58543d21e5cd41eab207beebd436745d`, `bm-biz_9435a1343a5e4486886e48ef3e4cb166`,
`bm-biz_978bf103aa8340dd94c187096d6a34c8`, `bm-biz_acadda31b09c48c7882292c98d5527da`,
`bm-biz_b9e854bac80c4f4dbff60b7e44f40340`, `bm-biz_ec22afb6d9144b4ba45a1fce883ed842`,
`bm-biz_fca251f35f814e7ca34f2bef977bf488`

### Group 4: start_time 2026-07-27 14:09 UTC (18 workflows)
`bm-biz_047abd395d6c48bda6ea652029d569c1`, `bm-biz_0e72b19022e94ec99c17a1fb19598039`,
`bm-biz_0f6b001e54774530ab60b726b3ee2878`, `bm-biz_16062d0fd05c433990ee1280c394880c`,
`bm-biz_26785db26fa4490d9c214716fcdfe6ac`, `bm-biz_2e15a254019348ec9e5202c1f37e51e4`,
`bm-biz_567cb108ca5347cbb9da73570055fc18`, `bm-biz_83564445561d4335bc4b50ecc8876d6d`,
`bm-biz_8d0d8d4cd4d54b41bd9644a6ccf58c0e`, `bm-biz_907b3dcae2004d4fb3bf81849f77533a`,
`bm-biz_a5fbc2d621fa4da09dbc19c08e015b7d`, `bm-biz_ba44ad22fd084b5b8c24cb2f4e8df6ef`,
`bm-biz_ba6c4be6741f459dafeae7ff38a3350d`, `bm-biz_c6d35d8da5514c4fb264d4bd626b399a`,
`bm-biz_d2e3ba5037ae44e19cf99ee70ec98c5b`, `bm-biz_e76a5558501a4b128721972c9def9691`,
`bm-biz_ef642df3cab44ab5a4999b4db89e4e1a`, `bm-biz_f5848f1bf1f7420caa94834ed942a940`

### Group 5: start_time 2026-07-27 14:12 UTC (9 workflows)
`bm-biz_420af0b036024692937258c1a1b6155a`, `bm-biz_518168dd58b44c4ea5754fd8eee71aeb`,
`bm-biz_65be3708fbc543899fde61e1b6cc2a5c`, `bm-biz_6bad04af8ac844cba68a3de091f763bc`,
`bm-biz_88213e8cb69b4447acbc21d895cc1d40`, `bm-biz_c236658426c24d6f949a2074997ea03e`,
`bm-biz_d8c35e8148bc43e2a66d9b3cb7148888`, `bm-biz_df12108cdb4441ceb7c5d24cae20abc1`,
`bm-biz_ea787afcae13412bad7a02a9c972aaf3`

### Group 6: start_time 2026-07-27 14:14 UTC (9 workflows)
`bm-biz_02bb3791ac8f4ff8902987b877ddebb1`, `bm-biz_072a1bc3b5f14abc9bcfae78edfa2289`,
`bm-biz_2824f451e046444bb171f6607a197d2e`, `bm-biz_68067b805f9d499aac62b1d56e3ec236`,
`bm-biz_868f8f2b8af14c529d263a94fc1d3d54`, `bm-biz_8e3aa0ea87c643fca3e09ce8c5e862e5`,
`bm-biz_8f809f4e52344fed94edba9ef4391752`, `bm-biz_d444c3d3d412438bbec40fa4eb1abe03`,
`bm-biz_d64e95a677d74904bc9eecba3922f494`

### Group 7: start_time 2026-07-27 14:15 UTC (9 workflows)
`bm-biz_070015560ed84709b08721f7ad5d7252`, `bm-biz_1af61299f0144bc786826401ade8192f`,
`bm-biz_38fd4333236d42efb8ca2f3afea514f1`, `bm-biz_3bb0af2fd0b744e1a197c092870e86be`,
`bm-biz_8b4ef6281fb74781a1120a3da5045dca`, `bm-biz_a3dddbb4eaf04af18c50a42d3e21580d`,
`bm-biz_dced213fe8bf4dadb38355fc0f2a86bf`, `bm-biz_de814f0bb139406889fc224ac50423e3`,
`bm-biz_fd53a91604e745b88bede450852987a4`

### Group 8: start_time 2026-07-27 21:29 UTC (9 workflows)
`bm-biz_2badaf3a0da44c5d89b6488221d4a510`, `bm-biz_3f626754d974424fa0de04ee0e50d1a7`,
`bm-biz_46dca5d6b98845c88ebe6af9f1152176`, `bm-biz_471262b3f8614f3b9e84ae2da17e79ea`,
`bm-biz_522dc6bb13fd46d6a58f85926ac7b3fa`, `bm-biz_8eee5b14f5784f99832e3c2c90ae171e`,
`bm-biz_9ef3626c11264467be65dc41bd336fef`, `bm-biz_a7b3c100c4954343b76083f20327f96b`,
`bm-biz_e8c4d501cd38468d8cd3c36d4c997b07`

### Group 9: start_time 2026-07-27 21:30 UTC (9 workflows)
`bm-biz_06c17b4bcf334093adddeca1b685b2ed`, `bm-biz_281800470549438f89a1aacfda77f8c6`,
`bm-biz_2d1b3d270dbb46bba26b7c89e6e3cf43`, `bm-biz_48f1fcc5fc0940bdace6bb1e86c23ea8`,
`bm-biz_5da2a2af4c804d44bc73a17096378e15`, `bm-biz_7b260cfa9fa7434699988b638a81c4ca`,
`bm-biz_88416325b66b48a59ef812d25af1f68e`, `bm-biz_f19d0895c20e44a08a9df9d12b6e7b5c`,
`bm-biz_ff23553c75ff4b88a0bc26179294e9ae`

### Group 10: start_time 2026-07-27 21:38 UTC (9 workflows)
`bm-biz_084f06fa9c834430b2492f4f239110ac`, `bm-biz_2e7b42d18c554942890be501ce377156`,
`bm-biz_3ca6d3a77519424c945e9ce947ca914c`, `bm-biz_4e915562ec9b4fb694f58b1f3be9edb4`,
`bm-biz_7594bb594f0c4f9eb1f1c73ea171c824`, `bm-biz_7b650b75a68b41e7b6b761452e3c1034`,
`bm-biz_97584e2c78fa46e69c1f57f5210eae35`, `bm-biz_baecc4100083469d851818d435519a0c`,
`bm-biz_c9808f3144fa454a9f8d8cab7b68c8e5`

### Group 11: start_time 2026-07-27 21:40 UTC (9 workflows)
`bm-biz_09a2640466a845958bbe5134b5e8fc84`, `bm-biz_21589ba1818d415abb6151f4dc17e06d`,
`bm-biz_63724f83212643d9bdf7c42fa5574c8f`, `bm-biz_6711fdd28c1247ad8f2b3e9a3e6bd664`,
`bm-biz_6b091ae3586c4a449ae4de20b407d78c`, `bm-biz_a3dbc792dc9741cea0576bab596c71ea`,
`bm-biz_b0fbda794e6b457197c65909b852544a`, `bm-biz_d895bc4fa73649caa074b73f1d3caffb`,
`bm-biz_f15cc4b28d2341b2a94c7788a9592ab5`

### Group 12: start_time 2026-07-27 21:46 UTC (9 workflows)
`bm-biz_1614eed7a99d43cb964ca0f092c71bb8`, `bm-biz_1983af36099745e69bcbc374267b26cc`,
`bm-biz_30802b611e974f23bf45929ac8b48399`, `bm-biz_4c5bf689916f4774b92a25f2c17e7a57`,
`bm-biz_4f3cbe37a65544dd97e9e1c64276d9ca`, `bm-biz_cf57d84141ba4dfab89a21f9513e3fc1`,
`bm-biz_e6009629c20b439fb2c96899bd55b158`, `bm-biz_f03e0b2a37a247b1a28df81f88597436`,
`bm-biz_fc106e8904324bce8c4013345fdc96f0`

### Group 13: start_time 2026-07-27 21:47 UTC (20 workflows)
`bm-biz_1db0b51b6d4f4c15a9049ca20d68b30b`, `bm-biz_2377ea5fafc2452fb82d6366f4bf843c`,
`bm-biz_2e42cabd094c4db9b0f686f12a2b1a38`, `bm-biz_5d0614f609ce42ec866ff11f2a6a1448`,
`bm-biz_62098b11cc2c4a83ab3d487a00f3f66e`, `bm-biz_6271afe5365c414fb4ea6e04338201ab`,
`bm-biz_677b384c37634350b817d287f1d12bea`, `bm-biz_7e546e9cb2ac4ffc9e40153dc2cc9601`,
`bm-biz_818aeb3191414c47a8c54e503f8e09b1`, `bm-biz_97c648c995184120bea3962b3834c0cb`,
`bm-biz_9cf787ccd47544e7b9e1521e1066768a`, `bm-biz_9dfff7b1e9b7421793829d7bb6842aa7`,
`bm-biz_b6e034134c034466942e62aabc97cc98`, `bm-biz_b75aac7ca97a4f2b845484438d0fd761`,
`bm-biz_bf11ec805317439cac7fc63ec9a91c82`, `bm-biz_c473e652f93946d69b7c89eac8ff26a7`,
`bm-biz_c908d31c1c1a40ba910d138b6eeb57c0`, `bm-biz_cf5e0e6b1f9b4e17a94c651648bde630`,
`bm-biz_e0dbed5a3c3746fab815f95e1cf51dc5`, `bm-biz_e445a8d16bb44165a73c615951e379ef`

### Group 14: start_time 2026-07-27 21:48 UTC (20 workflows)
`bm-biz_0e529076a965484da8358f6b7847c7fb`, `bm-biz_16c40421301d471bae33a2b45a0f1558`,
`bm-biz_314f02eece1c4fdfb15de9d95437e060`, `bm-biz_378f00eee97241619c5adb72f986e27e`,
`bm-biz_3a778802a16d44b9af3cdb1f186ca718`, `bm-biz_3c0f525d7f8b4f0db0fdf3e22b23740d`,
`bm-biz_3dec3c365ff84d46aac5b9170f0d8292`, `bm-biz_66b8bd4adb8443da91b2b2017414ab30`,
`bm-biz_79e44afd0e0041d4ade96ef0a4151597`, `bm-biz_7eeffa0b78444e32b273409d6580d436`,
`bm-biz_82e4652b0e8940b294b4c851075fb2b0`, `bm-biz_8848dd6ecffb44809f42c470d7ec0d8e`,
`bm-biz_9d9a00f95dca4c7bb175112ec7c17e41`, `bm-biz_9d9bf115889e49119c2a212262cd2479`,
`bm-biz_b2f522bff9594565b5fb3c68c1cbbf3a`, `bm-biz_c10d5a976ab14ee2a6bb1cbc697ea88b`,
`bm-biz_c4ef309909e14808a4dbdd7c01d53db4`, `bm-biz_cd83badd0523461a97475d1c502c3a4c`,
`bm-biz_edec484f187b464eb9c3268c8dc7778a`, `bm-biz_fa0f067486a6479c8c393119a2f139a4`

### Group 15: start_time 2026-07-27 21:49 UTC (11 workflows)
`bm-biz_0039554cb6ab4d6ebe35be1c38afca3f`, `bm-biz_015975491a1e4e098e9d2dca843327ce`,
`bm-biz_0faefc750aed46d68529aff6aaddfcfd`, `bm-biz_13b5d13272ce448985b6a52d1a3e0001`,
`bm-biz_2871ddaf6695429185d7de46ae227f14`, `bm-biz_44e7dddf40664ae99c3c1591e42d05a9`,
`bm-biz_c41c9def49b54abc82a33f6582988c12`, `bm-biz_d1fb0e7d4d254595b09f160ed1afff58`,
`bm-biz_e7c9b57d8b4a45a484d5f6c5a80fe98b`, `bm-biz_e9a548b1fe18456d8a5dc9aaec243a63`,
`bm-biz_f474c97a714c43719955bee152c2ea89`

### Group 16: start_time 2026-07-27 21:50 UTC (29 workflows)
`bm-biz_0263fe4b357a4584b0f219f3eab52084`, `bm-biz_029f3844814846e78798c5aaae8d1ec7`,
`bm-biz_11d0105fef4f435c82c6037ef2429c7f`, `bm-biz_11ed5db3c0c64d2fab46eb582a921430`,
`bm-biz_1de1f98ef9ff4803bc4e2360d095f1af`, `bm-biz_391c81b67bf94ab5acacb44023e4fd01`,
`bm-biz_51201416ccec4f12a8fe0732a0886c61`, `bm-biz_6d6e5c8fd2624e79bad7f2bba46a792f`,
`bm-biz_8cf5365361194e398a42ed96d5d9e4ec`, `bm-biz_8dfa3618148546c9bb28fda5cf576de5`,
`bm-biz_92d46c42fa4e471da7bd7eaaa2298126`, `bm-biz_9990552d8b1c4c4193425bc442c3525b`,
`bm-biz_9bbb63edd3554b11a2cc3845b12e0a3a`, `bm-biz_9bcd3b662ac14e32bad3ce7c05bcac3d`,
`bm-biz_9f8081cd885d42aaa014a84968062f81`, `bm-biz_a20d436563154131bc938a367c6943e4`,
`bm-biz_a7b64bb164524fc7915c7bc153d5c322`, `bm-biz_be7afe10db144b2a89ec69ba5aba855b`,
`bm-biz_c864a8469fbc48f584c8fe0f4becd1a0`, `bm-biz_ce5d6c6b85ee42b6a1c09afef55c5472`,
`bm-biz_d1a4d4a2933a4d108377836432982d05`, `bm-biz_da4c5c6eac214becbbdde8e6fd45a68c`,
`bm-biz_ddfbd1690bf04a01b511ba5e8dfb6c88`, `bm-biz_de92120125894841af7692f4fbebd199`,
`bm-biz_e6d3b8ceff2d4bc8bccd0603d2981fb4`, `bm-biz_eae9e0d181144a01aea2fbfea6c407a6`,
`bm-biz_eed25d4c983440ae8a6d6cbec73a468d`, `bm-biz_f62b13ea3d034097a7e22ed79104eb4a`,
`bm-biz_f6c02318594240d1836c5ff54dd04a2c`

### Group 17: start_time 2026-07-27 21:51 UTC (20 workflows)
`bm-biz_0853f2c4ba8a4021a58889a39c5e19de`, `bm-biz_1c02e483d948492abecab2a10387953b`,
`bm-biz_359f2c941b8843ada5e7908461c379c0`, `bm-biz_4166221ce72f4177b6d4c7e073022a7d`,
`bm-biz_5b6f88ebce9c47f0988cc2bbf210f25e`, `bm-biz_644fff775c0c462b8b0a12960a2d161d`,
`bm-biz_7cf06b7f86604f24a24dd0fe7c162940`, `bm-biz_7e8e00f45c8f46a7a4854c4dcc2ee5e6`,
`bm-biz_813163e1b60d4678b353b604d11a706a`, `bm-biz_a4903f7d40204863b35b61d576c57c8f`,
`bm-biz_ac13ae466d424a1d88421032f78d8686`, `bm-biz_d037f82fbc914d34aa953fccb1d1779d`,
`bm-biz_d3ab9a348523433ab4f249f6231b5650`, `bm-biz_d46f29a1817c4ec1bf231036590ec7ad`,
`bm-biz_f01f58b62ba24eca838e8e1de012cc8c`, `bm-biz_f3cb106c49dc421189340249b7721ae9`,
`bm-biz_f72ea17356bc4a2b80aa9c6fe3efda8f`, `bm-biz_f8b6c6176e2347eb94a2d60dc0a69307`,
`bm-biz_f9f8ceea67e64b2ab977a153aac30e63`, `bm-biz_fe29f42605ce4507b39128ae53ab018f`

### Group 18: start_time 2026-07-27 21:52 UTC (20 workflows)
`bm-biz_13191bc5b96b4aa7812a0778e88d0765`, `bm-biz_28eae4ca9aa546fb9e332fb84e1428c8`,
`bm-biz_40b5985698d246f3877c3cc8c96753cc`, `bm-biz_4d128a51de3842bba8dc133921f5272a`,
`bm-biz_5e8184e5151e4e83b8bc7235a2216c2b`, `bm-biz_6d43aa41e277409eb075b975cc223850`,
`bm-biz_7cb71acb810d41b9a73af8f48eb90427`, `bm-biz_8beb2153cab64d29a015a77be3c51675`,
`bm-biz_9677ce64750e4c77b2f9c7aeaa518775`, `bm-biz_b5ef9b210f5549439bfc28f899c4ca35`,
`bm-biz_c123ebe91567460bb00831964a5f5cdc`, `bm-biz_c798a017a62448b196df4e9553ce9751`,
`bm-biz_cee07d0130794bf08fae797b910e946c`, `bm-biz_d302f4ec785f46b497c7299ca6265a34`,
`bm-biz_d3af398214d043bdb886f239d88fafef`, `bm-biz_d83e207b64be4619baed5049b6bb3416`,
`bm-biz_de657ae630bb47c58686714349f887a9`, `bm-biz_e046769e2384429da09468c42170a9fb`,
`bm-biz_eb413a17f7454b2ea4e534155d9bbe5a`, `bm-biz_fbe608b15df84d648b31d51d8f210d07`

### Group 19: start_time 2026-07-27 21:53 UTC (11 workflows)
`bm-biz_1216d6f633fb4536a39750e41a250c63`, `bm-biz_1bfe7d3bf07343eeb2d69d128d2022b7`,
`bm-biz_3daa316bb68741f38aacb3ef15b3723e`, `bm-biz_5623400a51e344f08330135fea1dc498`,
`bm-biz_80e1b9ef0aad469fb9e2c4b04347cf8e`, `bm-biz_86d94db3307f41e7aadfe6c7fee5c666`,
`bm-biz_8e809932741845db94c61bb192618d20`, `bm-biz_8f8d2936600848e592b9e6640c4f62ae`,
`bm-biz_93d5cec9ce524e3eb095779a6a51d034`, `bm-biz_a5adee1d766d4326aa84ddb4fc503a8d`,
`bm-biz_e422c0c4044d4e99ba2ab74674b76ca5`

### Group 20: start_time 2026-07-27 21:58 UTC (9 workflows)
`bm-biz_65389219c41f4f7f80912ce341a793cc`, `bm-biz_7106b9849960409e8d1dd9f8413496c4`,
`bm-biz_7f3ccd7d618d430f86146f2332416b46`, `bm-biz_8321f4ecdd414f609635b25e6e4e8da7`,
`bm-biz_9f6d235958474662aad1d2f62a82541e`, `bm-biz_a5c16d02a20e43769cab447275f3a4ea`,
`bm-biz_aee80450d00f4e7e9b37c8339f07ae10`, `bm-biz_b04f235813a84cbcb03aebb28e4b9e8d`,
`bm-biz_fd8c7de0cfce4416a62e739c29615d1c`

### Group 21: start_time 2026-07-27 22:02 UTC (9 workflows)
`bm-biz_35765e0456c54fa8a5ebb32f71982943`, `bm-biz_6f1e437c63b146869522df15f28f9c36`,
`bm-biz_776c552bf91a4f5383628be5e5e7be49`, `bm-biz_7b4eadc86e9043679b5938ba29b68a4a`,
`bm-biz_a1534172f7e74f55ad541e84ffc4739f`, `bm-biz_b9724969338f4406af1b293080b67dff`,
`bm-biz_f2f4216ad4744c1c9cbec26e461668ba`, `bm-biz_f3290015ef2345f0af44851d3b2e007c`,
`bm-biz_f934fe680233464295c9647ad23bdb72`

### Group 22: start_time 2026-07-27 22:07 UTC (11 workflows)
`bm-biz_42260daed3454145b909ddc40102ec76`, `bm-biz_43145e844fee4c3fb9eafd8bf0524b7d`,
`bm-biz_540fba67da4c418a86efb292f5edf2ec`, `bm-biz_84079b457c6d4019b1141e423976c202`,
`bm-biz_88f3a2f6453a44c9808419129dbdfac9`, `bm-biz_9c5bb61ea48741c581b16b8135ba4a99`,
`bm-biz_a70367ff5dfd498497903aa27eb938bf`, `bm-biz_a97d6fbed2254d0589f3cae08598fabb`,
`bm-biz_bf3cb42318bb4861a27b0ced904f36e8`, `bm-biz_c7030ecf1f8c4d58b47832ab89fc4d6f`,
`bm-biz_d83d80e116d948ec9b72bbd8d8bc9e68`

### Group 23: start_time 2026-07-27 22:08 UTC (11 workflows)
`bm-biz_0fa64d08dbb248b6a71b2d13e7f76be1`, `bm-biz_185b8d1823ee4efcb0203e97da92db47`,
`bm-biz_38d2cadbcc4a4cd9ad46dab8945098fd`, `bm-biz_3937e00060914df9a6d454c3b2f274fa`,
`bm-biz_5564ea69480a417eb62323b46c30c992`, `bm-biz_5c3b83f4c8df42b7a7f07fa6b2316b39`,
`bm-biz_66ed27d483ab4b56aee1541878874c76`, `bm-biz_88e7235f2b214f50b2af5b8626abeb54`,
`bm-biz_96db5379d70646c8a1ced58cdb136577`, `bm-biz_993ff999764343c89f850d9dd0a5c39b`,
`bm-biz_b77e7c8ff9654911bd9a72b772cc03d9`

### Group 24: start_time 2026-07-27 22:09 UTC (11 workflows)
`bm-biz_156559b6714541b4a8e23169c986a4cc`, `bm-biz_208fa697d4c54808b2962742a41ceadc`,
`bm-biz_287cd6be781e43a799d43e4bdc1e77ec`, `bm-biz_2c705907835a4b6cb86ca05001317cc6`,
`bm-biz_2fada41f3a0b4e929c309a56a9ae6d2e`, `bm-biz_35d30d4c4f0f42bf990f635146a52ac8`,
`bm-biz_3d6443942f944cfaa93f31947ae9daef`, `bm-biz_756e0adf638147a7aeb66c1d3a5addbf`,
`bm-biz_9981a66973704f71920467f3e9607c86`, `bm-biz_c69badcbdb224508b6cb8a05a06db1cb`,
`bm-biz_f6ba9021a07e4df5865da0672c3ac643`

### Group 25: start_time 2026-07-27 22:18 UTC (11 workflows)
`bm-biz_0227eb5d3bfb47c4ac837ccaadfb3f56`, `bm-biz_06339497b615487b8dff6d2146d51d5d`,
`bm-biz_1e8069d51f6843b9a088bd101f3ff066`, `bm-biz_20915a8ff68c4e799095fbd0547cac91`,
`bm-biz_47c0bfc65077415c851027e35f377886`, `bm-biz_6ff2958231a9421b9f813e1e8d019531`,
`bm-biz_987bb02f7e9a4e36bc38d003460ba572`, `bm-biz_9b4140cf58b0445e91113c46033dac10`,
`bm-biz_b356442c731d4cfc868f9e5871bedbfb`, `bm-biz_dd6607954a1d42dd96b26e5d1802e62f`,
`bm-biz_f7f7ec994d6d4996894f94a0557ea42b`

### Group 26: start_time 2026-07-27 22:30 UTC (11 workflows)
`bm-biz_40e7e2b3a3cc43f8afe8c40b727fd3c4`, `bm-biz_4de8532624f94ad89b0e68117960472a`,
`bm-biz_53ab5fd605ed41a4bc136cd3dbd5b085`, `bm-biz_5be053400abd43b587bc40b8fb222534`,
`bm-biz_65b5b360e7a540c1b9a3e22711750670`, `bm-biz_666200c6520e4eab96e5afe4ae8e9b92`,
`bm-biz_8c2a680cbc0f42faaf63169b37c36a59`, `bm-biz_b624bcd438114792838a761650dd2c5e`,
`bm-biz_bfdbd8c8e2fb4df89dadceae0ae32ea1`, `bm-biz_c40c3be9d0884ac48c7e15c20c9595b3`,
`bm-biz_e76e1b158a034c7abba5b1f5973de787`

### Group 27: start_time 2026-07-27 22:31 UTC (22 workflows)
`bm-biz_065548c817e649fcb04c57328784003b`, `bm-biz_0b2e973a4f8c45baa27e487b4097148b`,
`bm-biz_17bda9c91067482798f8a4aa453b0811`, `bm-biz_2722af0ad8f14e16b844029228a5bbaf`,
`bm-biz_2ea1fe6d11d94ca0811bcb3f94e488cf`, `bm-biz_36d1a8bf31914652a67a5db4c9b9dc70`,
`bm-biz_42c78b3a703d49b285fedca9305641cc`, `bm-biz_487d1d38c3b24e69972f88ed9393793f`,
`bm-biz_709d9e9a35e34c399e50caeef68379b3`, `bm-biz_73e95d48e0344e0a8ec6b3118b8f73bc`,
`bm-biz_78fffbf1e2674114a8874fb034cce3fe`, `bm-biz_7f79b9f2e27f4bc4b0a7fc1a6e8fca48`,
`bm-biz_acf00f242d7b42b38c4b63dcea36d53c`, `bm-biz_bc52401fcb774e24a00d8e48ad2d2246`,
`bm-biz_be71fe740af64e57ab0d00c628f79104`, `bm-biz_d45b0a8f1da94c27a7635c6adf6b892d`,
`bm-biz_d66a15b2a84940aeba06e623d8a939f1`, `bm-biz_d963375e7b654aee81f7b4e52238a726`,
`bm-biz_de2bb08ce57d47db941c4751db9dc645`, `bm-biz_e69f7c7ca78b43798de81a9a144701fb`,
`bm-biz_f3dee641807f43809581f75dd8a7ff5c`, `bm-biz_fee69d61fadf4529923b0705a8b02884`

### Group 28: start_time 2026-07-27 22:33 UTC (11 workflows)
`bm-biz_223935540c524789993e897c7bd3aa80`, `bm-biz_2db65bac5a9348c0abba30c3e973bcdf`,
`bm-biz_3511141c2ffb4ff0b5227f426138964e`, `bm-biz_3a3cb35ef4164eb7809e71fd2d5e6ef4`,
`bm-biz_646ccfb46ce64c39a400445e2156261e`, `bm-biz_6ef13b7d5ccb45829120649c86d34aa1`,
`bm-biz_8cf0ec7cceab498d998aac675bb455e9`, `bm-biz_9df11d2ce74347f4898e6036906d6f10`,
`bm-biz_a24aa8c27d214d748ff4c247729775e6`, `bm-biz_bb701c3fe23f47629f7efa57b297166a`,
`bm-biz_c6232ef6f98247df825c3939728fbd21`

### Group 29: start_time 2026-07-27 22:34 UTC (11 workflows)
`bm-biz_0bc8931bbeb44666bd1453686bf9ba69`, `bm-biz_2678d62ff5584f129253bcdeadb131cb`,
`bm-biz_2ab63fd5cd0e47198a24be4923b12765`, `bm-biz_3b8ef1b615da477fb85361416c17471d`,
`bm-biz_723fdd233b4247c98079650c189e7bec`, `bm-biz_75a687cb76bc4189b8bc4438d066642d`,
`bm-biz_adf0d9eaeb54427e87a64ccc80b59348`, `bm-biz_ccfa31742f54494090d261aa847e6a50`,
`bm-biz_d5d3523a88f9480aa5b4a32dadadfa31`, `bm-biz_e881807232ab45d5915717d2a3354c43`,
`bm-biz_f0b0fe024ff0489dbcff7f110f14221f`

### Group 30: start_time 2026-07-27 22:35 UTC (11 workflows)
`bm-biz_09e9d0df4b314d49a31176b0461cc232`, `bm-biz_136281aed47e4349a96a03d701bdb889`,
`bm-biz_227de3e46af94b1d8e1373bd5f1393c1`, `bm-biz_79830322bbfe4eb6a3f33485f08f10be`,
`bm-biz_9e7c0ebe350e4f4c90e3fa76b7a3f0ac`, `bm-biz_aa1c85812976448ca17d533affcb360a`,
`bm-biz_bbd14563875542ceb32df2243880a96d`, `bm-biz_c37256a2e603457d976ce962d3980f80`,
`bm-biz_ceacf054ede54e56a3ab02dac1793a0c`, `bm-biz_d9239246e0a64fffae56d7c3f16ac0a1`,
`bm-biz_e697014c4dca4141ad3d5a7e8be10785`

### Group 31: start_time 2026-07-27 22:36 UTC (22 workflows)
`bm-biz_1fa537af921b4809b85ff60de5bd15d9`, `bm-biz_274b3f12c2fa442ab7876e3a823cf2d0`,
`bm-biz_2a8797e3145540379952dcfeffd6fe15`, `bm-biz_2b0aaa3e810c4b909d89db2db2e2df0c`,
`bm-biz_32cd75c8754e4ab3b378a489b649dd43`, `bm-biz_3bd5354ced8742adb3d941ae3ffade65`,
`bm-biz_3db0389d458d49a68a9e120b85b09074`, `bm-biz_5cb9337b565a4a3a9cabbc206e703470`,
`bm-biz_5efa9d7b3e5444dba2be9574f295b0ee`, `bm-biz_60d6da2f76d3402a8263f4f3b114d6e5`,
`bm-biz_6ad877951e4746818084351f30bd6c71`, `bm-biz_8edd0fdb3b1b42e68dd7821ec1afd75c`,
`bm-biz_9c7900288bca48f2989c070e8d6580c0`, `bm-biz_a5a210c01d4c4ffd8af9cbb039a82f7c`,
`bm-biz_b3bb88e297cd4bb58fce8f3f393da8a3`, `bm-biz_ba291fab1793452997a27c22940dfb83`,
`bm-biz_ccc8385c83fd470a8b2f994dfc56a669`, `bm-biz_ccd2dcda232d4bb3baf3de681bffc982`,
`bm-biz_d98482f0ca4849f38a66768e8b40dc7f`, `bm-biz_df05eb42461541b5ac6f2272ab0efd44`,
`bm-biz_e68c6437439f470f84003d482f204d37`, `bm-biz_ed3c769f6a7b49689730e999dd828d19`

### Group 32: start_time 2026-07-27 22:37 UTC (11 workflows)
`bm-biz_112ba797b25748bea50e3264cb7bf1ba`, `bm-biz_39b573fa9a7f4199be9fcbbd5adb9857`,
`bm-biz_3adda155b7ba4fd4ab8ee3cf50abbc10`, `bm-biz_6ac1c6769aa34df5a90b6dc25883b114`,
`bm-biz_767148ef0948443bbaca8ba2c614bb43`, `bm-biz_7b1582768ed64d7cbd67f8950b77850e`,
`bm-biz_803066d6931747dc8be21f2c142cfe9f`, `bm-biz_863bd09508ce4a1783259b443dde2860`,
`bm-biz_c21acc4ff3714af580d283ad6bb788f7`, `bm-biz_cd87b9c94f1e460582021c375cac1000`,
`bm-biz_ce1cfdbf96274b76929d20f52c93c17a`

### Group 33: start_time 2026-07-27 22:45 UTC (22 workflows)
`bm-biz_0bbd5eb88169450f8636786c36bc5756`, `bm-biz_1435bc24dbdc4c529a839569bd69e36f`,
`bm-biz_26b268a2d485442cad2b2b6dda425723`, `bm-biz_3087ff7717d44683a61e5408e2e0ab0d`,
`bm-biz_334e2d7a90e54e748da4e40393f26381`, `bm-biz_430a9eaa314147a8af95e8219c9be51c`,
`bm-biz_453ff56e5c38467a99a2f1251094157d`, `bm-biz_4aa8e1ee2d8b4d90be9dbf8642aefca9`,
`bm-biz_56d2601dc9f44289820623cb1aa31807`, `bm-biz_62d93596aead4be0b69b2c3ef84d6658`,
`bm-biz_768b17e9bef840d99061c63797cff49a`, `bm-biz_7d7ac5b2cb464a67946c15f07106ae96`,
`bm-biz_8eb2e57b239f424386ec044b46cc388c`, `bm-biz_9b207dee8dc44133843b029907a210c2`,
`bm-biz_b6db0ad4b3744ba5973125a6251b25fd`, `bm-biz_c1163fa2ef604305ad2a4180b50cf278`,
`bm-biz_c529e4733f5e46c7bbb16a525742fb81`, `bm-biz_ca19182c959b4221aef38e0eca1bd3d4`,
`bm-biz_cf90d2ad02c14c19b2fd98b3af9faaec`, `bm-biz_d531bb41b99c47bb93f364688f764d66`,
`bm-biz_e859b765862d4275b375fbe872ea565e`, `bm-biz_f188f9cfb4af4531a318f386ad732c78`

### Group 34: start_time 2026-07-27 22:46 UTC (11 workflows)
`bm-biz_04dfea13dffb418cbc0d685ad53fc6a7`, `bm-biz_05bff8e8d4fb4de9b681401029bb2fa0`,
`bm-biz_10d2edeab1894667804ef3c3b558598b`, `bm-biz_3d4fdfa5c85f401d8af69e77438675cf`,
`bm-biz_42fb8cefdad0424eb0d2c4a9493b8979`, `bm-biz_5a3bd1ba961f4932aa065971cdddee9f`,
`bm-biz_94ee7b54647f4079869cad24c1699a0e`, `bm-biz_97444541ddc24deeb9f6d4fc81cf0ec6`,
`bm-biz_9a73a1d75cfe4304932faba30ea0a28f`, `bm-biz_b198bd18ef6742c9855013f6c56421ae`,
`bm-biz_c7787fa2cc284d869d9370972edf9993`

### Group 35: start_time 2026-07-27 22:53 UTC (11 workflows)
`bm-biz_192e5cfa25eb437ab0a8d6654e27d1db`, `bm-biz_198c307b730f47ca958ea9be70dfa3e3`,
`bm-biz_203194b39b9c4c62b319f742414f21d7`, `bm-biz_2380afb013544224834940d0d03045a4`,
`bm-biz_47f7374ea77c4becbf4daea3d2a18070`, `bm-biz_7a135445e99b4720b52c0e0936b22bcd`,
`bm-biz_7e2568d4692d49f48e4502210fc53cf3`, `bm-biz_a8f9ba52fa9046ababbc5287114dc0d0`,
`bm-biz_c197e209ceec429ab4475abb32f36a0d`, `bm-biz_cbfaf8f1a82047fdb327d500372a4232`,
`bm-biz_fc099da1ebe542548bc633597e4046d3`

### Group 36: start_time 2026-07-27 22:55 UTC (11 workflows)
`bm-biz_5567b4043c324d0f99edb2ca6f4304e0`, `bm-biz_5e585fd540eb4780aa403a069a64dea9`,
`bm-biz_6c7e42f99b4c43b3a42809895372d636`, `bm-biz_73bee1398d67432b812a71a2623ec33f`,
`bm-biz_8073f218a0a94cfe900b933adae28151`, `bm-biz_83683cae2c754ffebdcd2c64fed1a7d5`,
`bm-biz_96de530323064d5a93a214a1475d22c7`, `bm-biz_98baf5b059b647fd9c0faaa5c42be7f9`,
`bm-biz_bc230ff552ee41ed922323a5d3024cba`, `bm-biz_de8c8a0f406f481d834f9ae96c4ba59a`,
`bm-biz_f7b08c873f9c466787a5aa3860be2434`

### Group 37: start_time 2026-07-27 22:58 UTC (11 workflows)
`bm-biz_10e309ecca574298b305ad19af2b1f8e`, `bm-biz_12b43e553271443db24ac7a0ff1e191c`,
`bm-biz_6890148ae3644b77a155ad36b351726c`, `bm-biz_92c4e005a5ef4141a04a457862fa97b7`,
`bm-biz_be2e8f77e3854d9ba35a5ef12cae688e`, `bm-biz_c363a5e710404bf196a950a93cae7fab`,
`bm-biz_d3a02211cb52462aa969edd860442502`, `bm-biz_ef57110c420c4d3f8120fb6a34de1693`,
`bm-biz_f085c14601174143a839c852b52b576b`, `bm-biz_f63c5fc4516c499da929279a918e85f3`,
`bm-biz_fde58793efa34c1a9fe6e5d2e2dcfdea`

**37 groups, 475 ids total (9+9+9+18+9+9+9+9+9+9+9+9+20+20+11+29+20+20+11+9+9+11+11+11+11+11+22+
11+11+11+22+11+22+11+11+11+11 = 475).**

</details>

## 4. Explicit exclusions

**Live `business_instances` table (read-only `SELECT`, live `jarvis` db, 3 rows total — the
complete table):**

| `business_id` | `display_name` | `business_type` | `lifecycle_state` | `created_at` (UTC) |
|---|---|---|---|---|
| `biz_6f548e12d9b145bfb53ed2e72f764b8b` | Trailhead Gear Reviews | affiliate | active | 2026-07-26 09:50:23 |
| `biz_5908873296374587aa15121f0a369ec1` | Summit Trail Gear | affiliate | active | 2026-07-26 11:36:45 |
| `biz_08122842a3034381abe3726d47464f16` | Portfolio Watch | finance_tracking | active | 2026-07-26 21:52:03 |

**The three protected workflow ids (untouchable, cross-checked live against the table above and
against Temporal `list_workflows`):**

- `bm-biz_6f548e12d9b145bfb53ed2e72f764b8b` — Trailhead Gear Reviews — confirmed **RUNNING**,
  `start_time` 2026-07-26T09:53:39Z (3 min after `created_at`, matching Manager-starts-on-activate)
- `bm-biz_5908873296374587aa15121f0a369ec1` — Summit Trail Gear — confirmed **RUNNING**,
  `start_time` 2026-07-26T12:29:35Z
- `bm-biz_08122842a3034381abe3726d47464f16` — Portfolio Watch — confirmed **RUNNING**,
  `start_time` 2026-07-26T21:52:33Z

All three are present in `list_workflows`, `status=RUNNING`, and their ids are exactly
`bm-` + the live `business_id` — no ambiguity found (the escalation trigger for "a protected id
is ambiguous" did not fire).

**Non-`BusinessManager` workflow types on `default`:** **none found.** All 478 executions
returned by `list_workflows("")` report `workflow_type = "BusinessManager"`; `count_workflows`
against the unfiltered query also returns 478. There is nothing else on this namespace to
mark untouchable — the escalation trigger for "any non-BusinessManager workflow types exist"
did not fire either.

## 5. The cleanup script (verbatim — NOT executed)

This is the exact script that would run on owner approval. It was written and reviewed as part
of this audit but **never invoked** — no `terminate` call happened at any point in this session.
The protection filter (`PROTECTED_IDS`) is the first thing in the file and every terminate call
is gated behind both an explicit id membership check and an explicit `--execute` flag; without
`--execute` it only prints the dry-run listing.

```python
#!/usr/bin/env python3
"""M8-F162 orphan purge — terminates every BusinessManager execution on Temporal
`default` EXCEPT the three protected live Manager ids. NOT executed by the
dry-run audit; owner-approved run only. Idempotent: a repeat run against an
already-purged namespace finds nothing left to terminate and exits cleanly.

Usage:
    uv run python scripts/purge_orphan_managers.py            # dry-run (default)
    uv run python scripts/purge_orphan_managers.py --execute   # actually terminates
"""
from __future__ import annotations

import argparse
import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

# ── protection filter — checked before every single terminate call ─────────
PROTECTED_IDS: frozenset[str] = frozenset({
    "bm-biz_6f548e12d9b145bfb53ed2e72f764b8b",  # Trailhead Gear Reviews
    "bm-biz_5908873296374587aa15121f0a369ec1",  # Summit Trail Gear
    "bm-biz_08122842a3034381abe3726d47464f16",  # Portfolio Watch
})
NAMESPACE = "default"
TEMPORAL_HOST = "localhost:7233"
REASON = "M8-F162 orphan purge"


async def main(execute: bool) -> None:
    client = await Client.connect(
        TEMPORAL_HOST, namespace=NAMESPACE, data_converter=pydantic_data_converter
    )

    before = await client.count_workflows("")
    print(f"before: {before.count} total executions on {NAMESPACE!r}")

    targets: list[str] = []
    async for wf in client.list_workflows(""):
        if wf.workflow_type != "BusinessManager":
            # Never touched, regardless of id — only BusinessManager is in scope.
            print(f"  SKIP (not BusinessManager): {wf.id} [{wf.workflow_type}]")
            continue
        if wf.id in PROTECTED_IDS:
            print(f"  SKIP (protected): {wf.id}")
            continue
        targets.append(wf.id)

    print(f"\n{len(targets)} orphan executions targeted for termination.")
    assert PROTECTED_IDS.isdisjoint(targets), "protected id leaked into target set — abort"

    if not execute:
        print("\nDRY RUN — no terminate calls made. Re-run with --execute to purge.")
        return

    terminated = 0
    for workflow_id in targets:
        if workflow_id in PROTECTED_IDS:  # redundant, defence in depth
            continue
        handle = client.get_workflow_handle(workflow_id)
        try:
            await handle.terminate(REASON)
            terminated += 1
        except Exception as exc:  # idempotent: already-terminated/not-found is fine
            print(f"  could not terminate {workflow_id}: {type(exc).__name__}: {exc}")

    after = await client.count_workflows("ExecutionStatus = 'Running'")
    print(f"\nterminated {terminated}/{len(targets)}")
    print(f"after: {after.count} RUNNING executions remain on {NAMESPACE!r}")

    for pid in PROTECTED_IDS:
        handle = client.get_workflow_handle(pid)
        desc = await handle.describe()
        print(f"  protected survivor {pid}: {desc.status.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="actually terminate (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(main(args.execute))
```

Expected effect on approval: before=478 → after=3 RUNNING (the three protected survivors,
verified individually post-purge); 475 terminate calls issued, each logged with the reason
string `"M8-F162 orphan purge"`, visible later in each execution's close event.

## 6. Root-cause analysis (ANALYSIS ONLY — not implemented this round)

**Root cause: an env-var name mismatch silently breaks Temporal namespace isolation for every
lane, and has since the isolation feature (OPS-1) landed.**

`jarvis/kernel/config.py`'s `Settings` uses `pydantic-settings` with `env_prefix="JARVIS_"` and
`env_nested_delimiter="__"` (double underscore). `TemporalSettings.namespace` is a *nested*
field (`Settings.temporal.namespace`), so the only env var that actually overrides it is
**`JARVIS_TEMPORAL__NAMESPACE`** (double underscore between `TEMPORAL` and `NAMESPACE`).
`model_config` sets `extra="ignore"`, so any other spelling is silently dropped — no error, no
warning.

Three places consistently use the wrong, **single-underscore** spelling:

- `scripts/lane_env.py::_env_block()` (line 242) prints
  `JARVIS_TEMPORAL_NAMESPACE={lane_namespace(lane_id)}` for a lane's `.env`.
- `.env.example` (line 14, and the commented lane template at line 40) documents
  `JARVIS_TEMPORAL_NAMESPACE`.
- `docs/DELEGATION.md` (line 476, "Lane environments") documents the same spelling.

Verified live (read-only, no side effects) with the actual `Settings` class:

```
JARVIS_TEMPORAL_NAMESPACE=lane-t1   (as lane_env.py/.env.example print it) → settings.temporal.namespace == "default"
JARVIS_TEMPORAL__NAMESPACE=lane-t1  (what pydantic-settings actually needs) → settings.temporal.namespace == "lane-t1"
```

So a lane that pastes `lane_env.py`'s printed block into its `.env` believes its Temporal
traffic is isolated to `lane-<id>`, but `Settings.temporal.namespace` silently stays `"default"`
— every real workflow that lane starts (via `ManagerLifecycle.reconcile()` /
`PlatformKernel.temporal_client()`, both of which read `settings.temporal.namespace` with no
override) lands on the shared live namespace instead. This has been true since the OPS-1 commit
(`f854945`/merge `8e3d7bb`) introduced lane environments — every milestone's lane work since
then that did any live-verification run (e.g. the M6-1/M7-3/M8-6-style "live run" packets) was
exposed to it.

Corroborating live evidence gathered this session (all read-only):
- `list_namespaces` on the Temporal server returns only `default` and `temporal-system` — **zero
  `lane-*` namespaces currently registered**, consistent with lane Temporal isolation never
  having actually taken effect via the app's own client, even where `lane_env.py create` was run.
- The lane **Postgres** override (`JARVIS_DATABASE_URL`) is a *top-level* Settings field, not
  nested, so its single-underscore-style plain name works correctly — which is presumably why
  this went unnoticed: DB isolation looked fine (only 3 rows in the live `business_instances`
  table, matching exactly the 3 protected businesses) while Temporal isolation silently failed.
- The 475 orphans' 37-cluster, all-today timing (§3) is consistent with repeated
  live-verification runs across lanes/packets rather than one automated pytest fixture.

**This is not a pytest-fixture bug.** I checked every test that references
`temporal_client`/`reconcile`/`start_workflow`/`Client.connect`/`BusinessManagerWorkflow`
(`test_manager_start_state.py`, `test_approval_roundtrip.py`, `test_manager_replay.py`,
`test_workflow_versioning.py`, and others) — every one either monkeypatches
`kernel.temporal_client`, injects a fake/capturing client, drives the workflow directly via
`ActivityEnvironment`/`Worker` replay with no live-server connection, or (replay tests) never
touches a real server at all. None of the current committed test suite starts a real workflow
against `localhost:7233`. The leak vector is manual/packet-level live-verification work in a
lane whose `.env` believed itself isolated.

**Proposed fix (not implemented this round):**
1. `scripts/lane_env.py::_env_block()`: change the printed line to
   `JARVIS_TEMPORAL__NAMESPACE={lane_namespace(lane_id)}` (double underscore).
2. `.env.example`: fix both occurrences (line 14's active default and line 40's commented lane
   template) to the double-underscore form.
3. `docs/DELEGATION.md` line 476: correct the documented variable name.
4. **Guard:** add a regression test (e.g. in `tests/test_lane_env.py`, which already covers
   `_env_block()`) asserting the *round trip* — that the exact env var name `_env_block()`
   prints, when set in `os.environ` and read through the real `Settings` class, actually changes
   `settings.temporal.namespace` to the lane namespace. That test would fail today (proving the
   defect) and pass once (1) lands, closing the loop pytest-fixture-shaped defects usually close
   via a red-then-green test.

**Why this is ANALYSIS ONLY here, not implemented:** the fix spans `scripts/lane_env.py`
(tooling, not a test file), `.env.example`, and `docs/DELEGATION.md` — none of which is a "pure
test-file change" I can fully gate in isolation per this round's mandate. The regression test in
item 4 *is* a pure test-file change, but a guard that asserts a round trip through code that is
still broken would either be written to fail (an intentionally red gate, not acceptable to land
under "gates in worktree if you commit any code") or would have to assert the current broken
behaviour as correct (worse than not having it — it would pin the bug down as a passing
contract). Landing the guard usefully requires landing the fix it guards; that's a single
follow-up packet's work, not a hygiene audit's. Recommending a follow-up packet: **M8-13,
lane-namespace env-var fix** (scripts/lane_env.py + .env.example + DELEGATION.md + the
test_lane_env.py round-trip guard, one commit).

## Commit

No code was changed in this round beyond this report file (docs-only). No `.env` file was read
or printed. `scripts/gates.sh` was not required to re-run for a docs-only change but the
worktree was confirmed clean before and after (`git status`).
