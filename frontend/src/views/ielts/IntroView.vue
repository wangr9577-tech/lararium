<template>
  <div>
    <div class="sub-head">
      <el-button text @click="$router.push('/ielts')"><el-icon><ArrowLeft /></el-icon>雅思主页</el-button>
      <span class="sub-name">雅思入门</span>
    </div>
    <div class="banner glass">
      <div class="b-t">雅思（IELTS）是什么</div>
      <div class="b-s">
        雅思是测评英语能力的国际标准化考试，由<b>剑桥大学英语考评部 + 英国文化协会（British Council）+ IDP</b> 三家联合主办；
        成绩被全球 140 多个国家、1.2 万余所院校与机构认可，用于<b>留学、移民、工作</b>。
        你出国读研，考的是<b>学术类（Academic）</b>。
      </div>
    </div>

    <div class="blk glass">
      <h3>分数怎么算</h3>
      <ul>
        <li>四项（听力/阅读/写作/口语）各 0–9 分，可给半分；总分 = 四项平均后按 0.25 进制取整（如 6.25 → 6.5，6.125 → 6.0）。</li>
        <li>常见目标线：本科 6.0–6.5、硕士 6.5–7.0；不少学校还要求<b>小分</b>（常为写作/口语 ≥ 6.0 或 6.5）。</li>
        <li>大致对照：6 = 合格使用者（能应付日常与多数学术场景）；6.5 = 良好；7 = 良好偏优秀，多数名校硕士门槛。</li>
      </ul>
    </div>

    <div class="blk glass">
      <h3>考试当天考什么（A 类）</h3>
      <div class="tbl">
        <div class="tr th"><span>模块</span><span>时长</span><span>内容</span><span>题量</span></div>
        <div class="tr"><span class="k">听力</span><span>约 30 分钟</span><span>4 段录音：日常对话 → 学术讨论/讲座，只播一遍</span><span>40 题</span></div>
        <div class="tr"><span class="k">阅读</span><span>60 分钟</span><span>3 篇学术长文（来自期刊/教材风格）</span><span>40 题</span></div>
        <div class="tr"><span class="k">写作</span><span>60 分钟</span><span>Task1 图表描述（≥150 词）+ Task2 议论文（≥250 词）</span><span>2 篇</span></div>
        <div class="tr"><span class="k">口语</span><span>11–14 分钟</span><span>与考官真人对话，3 个部分，通常在笔试前后单独进行</span><span>3 部分</span></div>
      </div>
      <p class="note">纸笔考听力结束另有 10 分钟誊写答案；机考只给 2 分钟检查。写作 Task2 占写作总分 2/3，Task1 占 1/3。</p>
    </div>

    <div class="blk glass">
      <h3>各科都考什么</h3>
      <ul>
        <li><b>听力</b>：S1 生活对话（租房/订票）→ S2 独白 → S3 学术讨论（作业/项目）→ S4 学术讲座；题型：填空、选择、配对、地图题。</li>
        <li><b>阅读（A 类）</b>：三篇学术文章由易到难；题型：判断（TRUE/FALSE/NOT GIVEN）、小标题 Heading、段落细节、填空、选择。</li>
        <li><b>写作</b>：Task1 描述图表（线/柱/饼/表格，偶尔流程图、地图）；Task2 就社会/教育/科技等话题写议论文，考论证与逻辑。</li>
        <li><b>口语</b>：Part1 日常问答（家乡/爱好等，4–5 分钟）；Part2 抽一张话题卡独白 1–2 分钟（准备 1 分钟）；Part3 围绕 Part2 深入讨论（4–5 分钟）。</li>
      </ul>
    </div>

    <div class="blk glass">
      <h3>机考还是纸笔？多久出分？</h3>
      <ul>
        <li>报名时可自选<b>机考或纸笔</b>；口语无论哪种都是与考官真人对话（部分地区可选视频通话）。</li>
        <li>机考出分约 3–5 天，纸笔约 13 天；成绩有效期 <b>2 年</b>。</li>
        <li>单项分数不理想可申请<b>复议</b>（成绩公布后规定时间内，复议若提分费用退还，以官网规则为准）。</li>
      </ul>
    </div>

    <div class="blk glass">
      <h3>报名与官方渠道</h3>
      <ul>
        <li>中国大陆通过官方报名网站报名（教育部考试中心雅思报名），考试费约 2170 元（以官网最新为准）。</li>
        <li>官方网站：<a href="https://www.ielts.org" target="_blank" rel="noopener">ielts.org</a>（全球官网，含免费样题与机考模拟入口）、<a href="https://ielts.neea.cn" target="_blank" rel="noopener">ielts.neea.cn</a> / <a href="https://www.chinaielts.org" target="_blank" rel="noopener">chinaielts.org</a>（中国区报名与信息）。</li>
        <li>备考以<b>雅思官方真题（剑桥雅思）</b>为主 —— 页面里的真题仓库即历年官方真题集。</li>
      </ul>
    </div>

    <div class="blk glass act">
      <h3>你现在的 2 个月打法</h3>
      <ul>
        <li>切到<b>「周计划」</b>页签，每天固定 1 小时按表打卡（单词已含在内）；前 6 周基础轮转，最后 2 周周六整卷模考。</li>
        <li>考前 1–2 周到 ielts.org 做一次<b>免费机考模拟</b>，熟悉机考界面与时间节奏。</li>
        <li>不确定的环节（如目标分、报考时间）建议先查官网或问有经验的人，别自己猜。</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowLeft } from '@element-plus/icons-vue'
// 雅思入门静态内容页（信息以雅思官网最新为准）
</script>

<style scoped>
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.sub-name { font-size: 15px; font-weight: 800; }
.banner {
  padding: 16px 20px; margin-bottom: 12px; border-radius: 16px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.1), rgba(167, 139, 250, 0.08));
  border: 1px solid rgba(56, 189, 248, 0.2);
}
.b-t { font-size: 19px; font-weight: 800; margin-bottom: 8px; }
.b-s { font-size: 14px; line-height: 1.9; color: var(--txt1); }

.blk { padding: 14px 20px; margin-bottom: 12px; border-radius: 16px; }
.blk h3 { margin: 0 0 10px; font-size: 15.5px; }
.blk ul { margin: 0; padding-left: 1.3em; display: grid; gap: 6px; }
.blk li { font-size: 13.5px; line-height: 1.8; }
.blk a { color: var(--acc2); }
.note { font-size: 12px; color: var(--txt3); margin: 8px 0 0; }
html.theme-dark .note { color: var(--txt2); }

.tbl { display: grid; gap: 0; font-size: 13px; }
.tr { display: grid; grid-template-columns: 52px 1fr 2.2fr 1fr; gap: 8px; padding: 7px 4px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); align-items: baseline; }
.tr.th { font-weight: 700; color: var(--txt2); font-size: 12px; }
.k { font-weight: 700; }
.act { border: 1px dashed rgba(167, 139, 250, 0.5); }

@media (max-width: 700px) {
  .tr { grid-template-columns: 44px 1fr; }
  .tr > span:nth-child(3), .tr > span:nth-child(4) { grid-column: 2; }
  .tr.th > span:nth-child(3), .tr.th > span:nth-child(4) { display: none; }
}
</style>
