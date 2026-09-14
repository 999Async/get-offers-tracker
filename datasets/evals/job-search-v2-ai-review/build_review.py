"""Materialize Codex's explicit JD judgments; never infer grades from retrieval scores.

Run with services/agent/.venv/bin/python. Unlisted pairs are explicit zero judgments
against the job's recorded primary duties, not unjudged candidates. Pending query
intent overrides all pairs. Equivalent query wrappers share the same rubric.
"""
import copy
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from getoffers_agent.job_search.contracts import JobInput, normalize
from getoffers_agent.job_search.evaluation import SearchDataset

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REVIEWER = "Codex (AI review; not human)"
# Each entry was adjudicated against the frozen full descriptions, not titles alone.
# Cross-role positives state the actual overlapping work and the boundary.
DECISIONS = {
 1: ("AI 数据采集运营管理", {
  1:(3,"负责采集量、质量、吞吐、贡献者增长和地区运营"),18:(3,"领导人类数据运营站点扩张，管理质量、吞吐、团队及运营系统"),3:(2,"负责住宅采集项目排期、预算和执行，范围偏项目协调"),20:(2,"负责数据质量审核项目、人员和供应商，范围偏质量而非采集增长"),30:(1,"负责数据采集设备物流与团队，是运营中的物流子环节")}),
 2: ("全身控制策略的训练、仿真与部署基础设施", {
  2:(3,"主责控制策略训练基础设施、物理仿真、集群利用和部署工具"),11:(2,"职责含 RL 分布式 rollout、仿真基础设施及实验管理，主要工作是 RL 算法"),21:(2,"主责全身控制 RL 训练与部署、仿真到实机迁移，偏算法而非基础设施"),13:(1,"训练性能、集群调度、数据加载及容错有交集，未指定控制策略仿真"),5:(1,"负责机器人数据到神经网络训练的传输和存储，覆盖数据管线子环节"),12:(1,"负责操作策略训练部署并使用仿真工具，非全身控制训练基础设施")}),
 3: ("住宅机器人数据采集项目的排期、站点准备与执行", {
  3:(3,"端到端负责住宅数据采集、排期、场地布置和物流协调"),4:(2,"规划机器人向住宅部署的物流并担任站点负责人，偏技术部署"),1:(2,"管理数据采集运营、地区落地和合作方，未聚焦住宅排期"),18:(2,"管理数据站点落地、设施、团队和伙伴，范围偏国际扩张"),30:(2,"安排采集设备运输、库存和调度，偏物流环节"),28:(1,"负责客户现场部署及测试，部分现场执行重合，未明确住宅采集排期"),29:(1,"负责客户现场部署及测试，部分现场执行重合，未明确住宅采集排期")}),
 4: ("机器人数据采集现场的工程部署与排障", {
  4:(3,"数据采集现场调试、commissioning、技术问题归因和工程反馈"),28:(2,"客户现场部署、测试、数据采集分析与调试，工作场景偏商业部署"),29:(2,"客户现场部署、测试、数据采集分析与调试，工作场景偏商业部署"),17:(1,"操作机器人并将故障升级给工程团队，属于现场支持而非工程部署主责"),3:(1,"协调采集部署、场地与机器人物流，不负责技术调试"),30:(1,"为采集及客户站点安排设备、备件与调度，只覆盖部署物流")}),
 5: ("机器人数据传输、存储、处理和访问基础设施", {
  5:(3,"主责机器人数据传输、存储、访问与云和本地资源"),2:(2,"职责含控制策略训练数据管线和训练基础设施，偏训练仿真"),13:(1,"优化数据加载、预处理和 checkpoint，覆盖训练端数据基础设施"),10:(1,"构建多节点分布式训练管线，主要职责为基础模型预训练"),14:(1,"实现高吞吐视频输入和训练数据管线，主要职责为视频预训练"),23:(1,"实现数据保留、删除、匿名化等数据服务，偏隐私治理")}),
 6: ("视觉、视频及多模态生成模型的设计训练和部署", {
  6:(3,"主责大规模 diffusion 等生成模型、合成数据与模型评估"),14:(2,"探索视频生成与 diffusion 架构，主要工作为视频预训练"),8:(1,"设计多模态模型及世界结构表征，未以生成建模为主责"),10:(1,"训练多模态基础模型并设计架构，未明确生成或 diffusion 主责"),9:(1,"感知模型职责结合 diffusion/VLM 领域要求，生成仅为可选专长")}),
 7: ("多传感器融合定位、运动跟踪与状态估计", {
  7:(3,"主责融合多模态传感器的实时定位、运动跟踪及状态估计"),24:(3,"主责实时与离线状态估计、视觉惯性融合和人体运动轨迹重建"),9:(2,"职责明确含 localization 且要求 VIO/SLAM 等领域专长，范围更广")}),
 8: ("视觉、语言和动作的多模态模型架构与表征学习", {
  8:(3,"主责感知、推理和动作模型架构，以及融合、对齐和表征学习"),10:(2,"设计多模态基础模型和预训练架构，偏预训练"),14:(2,"设计视频模型架构与时序表征，模态偏视频"),6:(2,"开发生成模型和世界建模，偏生成建模"),12:(2,"设计视觉运动策略并采用 VLA reasoning，偏操作策略"),9:(2,"开发视觉、定位与视觉运动感知系统，偏感知应用"),11:(1,"训练具身策略与长程行为，涉及动作学习但主责 RL"),13:(1,"与研究员协同设计模型架构和训练配方，目标为硬件效率")}),
 9: ("机器人视觉、定位与视觉运动感知系统", {
  9:(3,"主责机载视觉、定位、视觉运动策略和离线标注"),7:(2,"主责视觉惯性定位与传感器融合，覆盖定位感知方向"),8:(2,"模型架构明确服务感知、推理和动作，偏模型设计"),12:(2,"设计视觉运动操作策略，覆盖视觉运动方向"),6:(2,"职责明确开发改善机器人感知、世界建模的生成模型"),24:(2,"多传感器状态估计和运动跟踪，偏遥操作及采集系统"),14:(1,"预训练表征迁移至感知与跟踪，未直接主责机载感知系统"),10:(1,"基础模型支持下游感知，主责预训练")}),
 10: ("大规模多模态基础模型预训练", {
  10:(3,"主责多模态基础模型、预训练策略、数据配比和 scaling laws"),14:(3,"主责大规模视频基础模型预训练，是明确的视觉模态子方向"),6:(2,"训练大规模多模态生成模型，偏生成建模"),8:(2,"设计训练视觉语言等模型，偏架构创新"),13:(1,"优化超大模型训练性能，未主责预训练学习方法")}),
 11: ("具身智能体强化学习算法和策略训练", {
  11:(3,"主责具身 RL 算法、奖励建模、探索及真实和模拟环境策略"),21:(3,"主责机器人全身控制 RL 算法训练、部署与 sim-to-real"),12:(2,"操作策略职责明确应用强化学习，同时包含行为克隆及 VLA"),2:(1,"训练控制策略基础设施、超参数和仿真，RL 算法非主责")}),
 12: ("真实机器人学习及视觉运动操作策略", {
  12:(3,"主责真实机器人视觉运动策略、抓取、双手操作及训练部署闭环"),11:(2,"真实及模拟环境具身 RL，未限定操作策略"),21:(2,"全身控制 RL 与 sim-to-real，偏全身运动控制"),9:(2,"职责包含视觉运动策略，范围偏感知系统"),8:(1,"设计动作和多模态模型并完成训练部署，未明确操作策略实机闭环"),2:(1,"将控制策略从训练验证部署到硬件，偏基础设施")}),
 13: ("大模型分布式训练性能优化", {
  13:(3,"主责 GPU kernel、并行策略、性能回归、集群效率及容错"),2:(2,"优化训练速度、基础设施和集群利用，偏机器人控制训练"),10:(2,"优化大规模分布式预训练管线，偏预训练算法"),14:(2,"优化视频模型训练的计算、内存和吞吐，偏视频预训练"),6:(1,"优化分布式生成模型训练管线，仅部分职责重合"),5:(1,"优化训练数据传输与存储，覆盖 I/O 子环节")}),
 14: ("视频或高维时序模型的大规模预训练", {
  14:(3,"主责视频基础模型预训练、时间动态、运动及交互表征"),6:(2,"大规模生成模型明确包含视频，偏生成建模"),10:(2,"预训练的数据源明确包含视频，范围为多模态基础模型"),8:(1,"世界动态表征及多模态模型设计，未明确视频预训练主责")}),
 15: ("穿戴传感器进行动作数据采集", {
  15:(3,"穿戴传感器引导动作并采集高质量运动数据"),16:(3,"穿戴传感服执行精确重复动作生成训练数据"),17:(3,"明确穿戴传感器采集运动数据，并兼做客户现场机器人操作")}),
 16: ("长时间穿戴传感服执行重复动作采集", {
  15:(3,"穿戴传感器采集动作，要求每天站立 8 小时以上"),16:(3,"明确每班最多 8 小时执行重复动作及动作协议"),17:(2,"穿戴传感器采集动作并需站立 8 小时以上，兼做站点运营")}),
 17: ("Fontana 客户现场的机器人操作与动作数据采集", {
  17:(3,"Fontana 客户现场直接操作机器人并穿戴传感器采集动作"),28:(2,"工作地点 Fontana，现场测试、采集分析和调试，偏工程师而非操作员")}),
 18: ("数据运营的国际扩张与新站点落地", {
  18:(3,"主责全球数据运营扩张、国际新站点建设及扩张团队"),1:(2,"职责包含新地区落地、伙伴及本地化，未承担全球扩张团队主责"),3:(1,"住宅采集站点准备与并行部署协调，未明确国际扩张"),30:(1,"负责国内国际运输与部署物流，覆盖站点落地物流部分")}),
 19: ("制造产线末端自动化测试软件", {
  19:(3,"主责产线末端编程、校准、验证软件和新硬件自动化测试"),22:(2,"开发制造软件并增加测试覆盖，偏 MES/WMS 等业务软件"),28:(1,"制定客户现场测试计划、分析数据并调试，场景偏部署"),29:(1,"制定客户现场测试计划、分析数据并调试，场景偏部署"),4:(1,"机器人 commissioning、现场测试及编码调试，非产线末端自动化")}),
 20: ("数据质量审核指南、验收准则与审核项目", {
  20:(3,"主责审核指南、验收准则、边界案例、金标集及审核周期"),1:(1,"负责采集质量指标与运营改进，未明确审核准则和金标集"),18:(1,"负责跨站点质量指标与流程改进，未明确审核准则和金标集")}),
 21: ("机器人全身控制的强化学习", {
  21:(3,"主责全身控制 RL 算法、策略评估、sim-to-real 和控制栈"),11:(2,"具身 RL 与策略鲁棒性，未限定全身控制"),2:(2,"全身控制策略训练及部署工具，偏基础设施"),12:(1,"操作控制策略使用 RL，未明确全身控制")}),
 22: ("制造系统业务软件与工作流开发", {
  22:(3,"主责 MES/WMS/PLM/QMS 数字制造软件和工作流"),19:(2,"维护产线末端自动化软件及技术员 GUI，偏测试系统")}),
 23: ("隐私增强与数据治理软件工程", {
  23:(3,"主责隐私控制、匿名化、数据最小化、保留删除及服务接口")}),
 24: ("采集系统实时和离线多传感器状态估计", {
  24:(3,"主责 C++ 实时滤波与离线批优化、传感器融合及人体标定"),7:(3,"实时状态估计、离线姿态跟踪管线及采集平台多传感器标定"),9:(1,"开发定位感知并要求 VIO/SLAM 专长，未明确双层采集状态估计")}),
 25: ("商业法务、数据和基础设施采购协议谈判", {
  25:(3,"主责 GPU 算力采购协议、数据权属、硬件供应链法律事务，要求律师资格")}),
 26: ("连接器和机电接口的设计与验证", {
  26:(3,"主责连接器 CAD、GD&T、功率计算、供应商及环境可靠性验证")}),
 27: ("硬件制造需求预测与供应链需求计划", {
  27:(3,"主责统一需求计划、预测建模、良率报废损耗与 S&OP"),30:(1,"管理设备库存可用性、使用指标和调度，覆盖库存计划子环节")}),
 28: ("商业客户现场的机器人部署工程", {
  28:(3,"主责客户现场部署、测试计划、数据分析与调试"),29:(3,"主责客户现场部署、测试计划、数据分析与调试；查询未限制城市"),4:(2,"主责采集现场机器人部署、排障与测试，场景偏住宅采集"),17:(1,"客户现场操作机器人并上报问题，非部署工程主责"),30:(1,"向客户现场调度机器人设备及备件，覆盖部署物流")}),
 30: ("机器人部署设备的仓储、库存、运输与团队管理", {
  30:(3,"主责仓储库存策略、调度、国内国际运输、设备追踪和团队"),4:(1,"规划住宅部署物流并保障工具备件，偏部署工程"),3:(1,"协调机器人物流与采集排期，偏采集项目协调"),27:(1,"预测需求、管理零件分配及库存风险，偏需求计划")}),
}
DECISIONS[29] = copy.deepcopy(DECISIONS[28])
# Requirements-only queries without an identifiable work objective stay unscored.
PENDING_REQUIREMENTS = {
 1:"只列投行、咨询、企业发展或运营经历；需确认目标职责和年限含义",
 2:"只列 Python/PyTorch 与软件经验；无法区分模型研究、训练基础设施等方向",
 3:"只列项目管理、咨询或投行经历；需确认岗位目标",
 5:"只有软件工程基础要求，未指定任何工作方向",
 9:"只有生产级软件/ML 工程经验，未指定感知或其他 ML 工作",
 13:"只有学历和专业要求，不能推断训练性能岗位",
 15:"只有身体协调、空间感和专注力，未指定职业或采集任务",
 16:"只有长期重复动作的体能要求，未明确要找何种工作",
 17:"只有全美出差意愿，未指定职业",
 18:"只有初创/跨国企业运营年限，未明确扩张还是其他运营工作",
 19:"只有 5 年以上行业经验，未指定行业和职责",
 22:"只有 4 年以上行业经验，未指定行业和职责",
}
# Narrower duty/qualification queries must not inherit all broad title positives.
OVERRIDES = {
 (16,'title'):DECISIONS[15],
 (4,'duty'):("现场工程部署与技术支持", {**DECISIONS[4][1],28:(3,"直接作为客户现场工程代表开展部署测试和调试"),29:(3,"直接作为客户现场工程代表开展部署测试和调试")}),
 (17,'duty'):("客户现场机器人的日常运行", {17:(3,"主责客户现场机器人的日常运行、维护和安全"),28:(2,"客户现场工程测试及性能保障，偏部署工程"),29:(2,"客户现场工程测试及性能保障，偏部署工程"),4:(1,"数据采集站点运行、排障与站点健康汇报，未限定商业客户")}),
 (20,'duty'):(DECISIONS[20][0], {20:DECISIONS[20][1][20]}),
 (25,'duty'):("GPU、数据中心和技术许可的采购协议谈判", {25:(3,"直接负责全球数据中心容量、GPU 算力和技术许可谈判协议")}),
 (26,'duty'):("连接器及机电接口的 3D CAD 和 2D 制造图纸", {26:(3,"直接负责自定义连接器、包胶和机电接口的 CAD 与图纸")}),
 (27,'duty'):("汇总需求预测与建模", {27:(3,"主责统一需求预测、统计模型和 S&OP 需求信号")}),
 (28,'duty'):("现场工程部署与开发支持", {28:(3,"主责现场工程部署、测试与调试"),29:(3,"主责现场工程部署、测试与调试"),4:(3,"主责现场工程部署、排障与测试"),17:(1,"客户现场操作、故障上报，偏操作员"),30:(1,"向客户站点调度设备和备件，覆盖现场部署物流")}),
 (29,'duty'):None,
 (7,'requirement'):("复杂状态估计及非线性优化", {7:(3,"主责多传感器状态估计且要求非线性优化专长"),24:(3,"主责实时估计与离线优化，明确要求因子图、非线性最小二乘"),9:(1,"定位感知职责及优化、VIO/SLAM 要求部分相关")}),
 (8,'requirement'):("视觉、语言或多模态深度模型的设计训练", {**DECISIONS[8][1],6:(3,"主责视觉和多模态生成模型的设计训练"),10:(3,"主责多模态基础模型的设计训练"),14:(3,"主责视频模型架构与大规模训练"),12:(2,"设计训练视觉运动策略，模型领域偏操作控制")}),
 (14,'requirement'):(DECISIONS[14][0],DECISIONS[14][1]),
 (20,'requirement'):DECISIONS[20],
 (21,'requirement'):("机器人动力学与控制，优先腿足机器人", {21:(3,"主责全身控制策略且明确要求动力学和控制"),2:(2,"控制训练和物理仿真，需要动力学及机器人系统知识"),12:(2,"视觉运动操作控制涉及接触动力学，偏机械臂操作"),24:(1,"人体全身运动学估计服务遥操作，偏估计而非动力学控制")}),
 (24,'requirement'):("评估新传感模态以指导硬件设计", {24:(3,"明确评估新传感模态、分析硬件限制以指导设计"),7:(1,"设计多传感器融合与采集平台标定，部分涉及传感系统设计"),26:(1,"连接器信号、电气接口设计及硬件验证，覆盖硬件接口子环节但不研究传感模态")}),
 (26,'requirement'):("连接器插拔、拉脱、振动及环境可靠性验证", {26:(3,"明确制定并执行插拔、拉脱力、振动、热循环和环境测试")}),
 (27,'requirement'):("将制造良率、报废及破坏性测试需求纳入需求计划", {27:(3,"明确把制造良率损失、报废和破坏性测试需求计入总需求信号")}),
}
OVERRIDES[(29,'duty')] = OVERRIDES[(28,'duty')]
# Shared ML vocabulary or a requirement-only optional specialty does not establish duties.
for job_number in (8, 9, 10):
 DECISIONS[6][1].pop(job_number)
OVERRIDES[(24,'requirement')][1].pop(26)
# Deployment experience is a sufficiently specific work domain, unlike generic years.
for n in (4,28,29):
 OVERRIDES[n,'requirement']=("汽车/工业自动化或机器人集成部署与开发", {4:(3,"直接要求相关集成部署经验，主责机器人现场部署"),28:(3,"直接要求相关集成部署经验，主责客户现场部署"),29:(3,"直接要求相关集成部署经验，主责客户现场部署"),19:(1,"机器人产线软硬件接口及自动化测试，与工业自动化开发部分相关"),12:(1,"学习系统部署到真实机器人，与机器人开发部署部分相关")})


def write_csv(path, rows, fields):
 with path.open('w', encoding='utf-8-sig', newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def sha(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
 draft_path=ROOT/'datasets/evals/job-search-v1/official-draft.json'
 draft=json.loads(draft_path.read_text())
 jobs={i:normalize(JobInput.model_validate(j)) for i,j in enumerate(draft['jobs'],1)}
 assert len({j.version_id for j in jobs.values()})==30
 labels=[]; decisions=[]; runnable=[]; pending=[]
 constraints='城市/招聘类型/排除条件未指定，按无该项限制评估；保留 max_age_days=90，全部冻结岗位满足；无候选人履历，不推断个人资格。'
 for case in draft['cases']:
  cid=case['case_id'];_,group,variant=cid.split('-');n=int(group);v=int(variant)
  kind={1:'title',2:'duty',3:'requirement',4:'title',5:'duty'}[v]
  scope, positives=OVERRIDES.get((n,kind),DECISIONS[n])
  reason=PENDING_REQUIREMENTS.get(n,'') if v==3 else ''
  if n==3 and kind=='title': reason='Data Strategy Associate 未明确数据运营、数据分析还是数据策略研究；不能借原正例反推查询意图'
  if n==13 and kind=='duty':
   reason='明确提及 100B+ 参数和 100k+ GPU；需确认数字是硬要求还是规模示意，其他训练岗缺少规模证据'
  d={'case_id':cid,'query':case['request']['query'],'kind':kind,'scope':scope if not reason else '', 'query_review_status':'pending' if reason else 'ai-adjudicated','pending_reason':reason,'reviewer':REVIEWER,'constraint_review':constraints,'labels':{}}
  for number,job in jobs.items():
   grade='';note='待确认：'+reason if reason else ''
   if not reason:
    grade,why=positives.get(number,(0,f'该岗位主责为“{DECISIONS[number][0]}”，与本查询“{scope}”无明确职责重合；公司 AI/机器人背景或通用技能不计相关'))
    if n==17 and kind=='title' and 'Fontana, CA' not in job.cities:
     grade=0;why='查询文本明确 Fontana 客户现场；冻结岗位地点为 '+', '.join(job.cities)+'，违反明确地点要求（原结构化 cities 遗漏该条件）'
    note=f'{why}。全文依据：{job.responsibilities[0]}。'+constraints
    d['labels'][job.version_id]=grade
   labels.append({'case_id':cid,'query':case['request']['query'],'job_version_id':job.version_id,'proposed_grade':case['relevance'].get(job.version_id,''),'reviewed_grade':grade,'reviewer':REVIEWER,'note':note,'job_title':job.title,'job_cities':' | '.join(job.cities),'review_status':'pending' if reason else 'ai-adjudicated'})
  if reason: pending.append({'case_id':cid,'request':case['request'],'reason':reason})
  else:
   new=copy.deepcopy(case);new.update(relevance=d['labels'],review_status='machine-proposed',reviewer=REVIEWER);runnable.append(new)
  decisions.append(d)
 # Identical requests receive identical dispositions and labels, across source seeds.
 signatures={}
 for c,d in zip(draft['cases'],decisions,strict=True):
  key=json.dumps(c['request'],sort_keys=True)
  value=(d['query_review_status'],d['labels'])
  assert key not in signatures or signatures[key]==value, c['case_id']
  signatures[key]=value
 # Freeze judgments before inspecting candidate membership. Ranking is never an input to grades.
 (OUT/'adjudications.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+'\n')
 (OUT/'pending-queries.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2)+'\n')
 revised=copy.deepcopy(draft);revised.update(dataset_version='job-search-v2-ai-review-2026-09-06-r2',cases=runnable)
 SearchDataset.model_validate(revised)
 (OUT/'official-ai-reviewed.json').write_text(json.dumps(revised,ensure_ascii=False,indent=2)+'\n')
 old=json.loads((ROOT/'docs/experiments/phase1-official-neural-paired.json').read_text())
 pools={c['case_id']:set() for c in draft['cases']}
 for report in old['reports']:
  assert set(pools)=={c['case_id'] for c in report['cases']}
  for row in report['cases']: pools[row['case_id']].update(row['ranked_version_ids'])
 assert all(p<= {j.version_id for j in jobs.values()} for p in pools.values())
 for row in labels: row['in_four_run_union']=str(row['job_version_id'] in pools[row['case_id']]).lower()
 fields=list(labels[0]);write_csv(ROOT/'datasets/evals/job-search-v1/label-review.csv',labels,fields);write_csv(OUT/'label-review.csv',labels,fields)
 with (ROOT/'docs/experiments/review-snapshots/phase1-case-review.before.csv').open(encoding='utf-8-sig',newline='') as f:
  cases=list(csv.DictReader(f))
 byid={d['case_id']:d for d in decisions}
 for row in cases:
  d=byid[row['case_id']];row['reviewed_labels']=json.dumps(d['labels'],ensure_ascii=False) if d['labels'] else '';row['reviewer']=REVIEWER
  row['notes']=('待确认：'+d['pending_reason'] if d['pending_reason'] else 'AI 复核：'+d['scope']+'；已判断全部 30 个岗位。')+' '+constraints+' 不是人工金标；旧模型排名和差值保留作历史记录。'
  row.update(query_review_status=d['query_review_status'],city_review='Fontana 为文本硬条件，结构化过滤遗漏' if row['case_id'] in ('official-17-1','official-17-4') else '未指定，不补造',exclusion_review='未指定，不补造',union_candidate_count=len(pools[row['case_id']]),judged_job_count=len(d['labels']),pending_job_count=30-len(d['labels']),positive_job_count=sum(g>0 for g in d['labels'].values()))
 write_csv(ROOT/'docs/experiments/phase1-case-review.csv',cases,list(cases[0]))
 counts=Counter(str(r['reviewed_grade']) if r['reviewed_grade']!='' else 'pending' for r in labels)
 manifest={'reviewer':REVIEWER,'review_date':'2026-09-06','source_dataset_sha256':sha(draft_path),'review_dataset_sha256':sha(OUT/'official-ai-reviewed.json'),'adjudications_sha256':sha(OUT/'adjudications.json'),'source_report_sha256':sha(ROOT/'docs/experiments/phase1-official-neural-paired.json'),'original_queries':150,'included_queries':len(runnable),'pending_queries':len(pending),'job_count':30,'label_rows':len(labels),'grade_counts':dict(counts),'review_status':'AI adjudication; human confirmation required','blinding':'Not strictly blind: original reports and proposed labels were seen during setup. Subsequent scoring used full JDs and query criteria without ranking scores. review-packet.json omits ranks, model names and labels for a future independent review.','metrics_scope':'Only fully adjudicated queries enter this AI-review experiment; original query text, requests, as_of and jobs unchanged. Pending cases excluded rather than treated as negatives.','deduplication':'Exact identical requests have identical labels. Template variants retained for historical paired comparison, not independent real-user samples.','reviewed_dataset_ready':False,'production_release_ready':False}
 (OUT/'review-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
