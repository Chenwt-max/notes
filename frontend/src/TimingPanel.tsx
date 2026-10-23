type Metric={seconds:number;completed:number;interrupted:number};
const labels:Record<string,string>={asr_stage:'字幕阶段（含子项）',handout_import:'已有课件读取与页面渲染',visuals_stage:'课件提取',compaction:'画面精简',ocr:'初步文字识别',formula_stage:'公式阶段（含子项）',quality:'来源核验',organize_stage:'整理与逐章复核（含子项）',deferred_review:'补充复核',chapter_export:'逐章导出',final_export:'最终导出',screening_stage:'课件筛选阶段',screening:'课件内容筛选',model_load:'模型加载',audio_decode:'音频解码',vad:'语音活动检查',recognition:'模型识别',alignment:'词级时间对齐',transcribe_total:'转写与对齐总计（含子项）',checkpoint:'字幕保存',cooldown:'主动休眠',organize_request:'整理接口等待',review_request:'复核接口等待'};
const names:Record<string,string>={pipeline:'处理阶段',asr:'字幕细项',screening:'课件筛选细项',formula:'旧版课件模型细项',synthesis:'接口细项'};
const duration=(s:number)=>s<60?`${s.toFixed(1)} 秒`:`${Math.floor(s/60)} 分 ${(s%60).toFixed(0)} 秒`;
export default function TimingPanel({value}:{value:any}){
 const groups=Object.entries(value?.groups||{}).filter(([,metrics])=>Object.keys(metrics as object).length);
 if(!groups.length)return null;
 return <details className="context-help"><summary>查看分项耗时</summary><p>累计已记录的墙钟时间，包含中断的工作。阶段含子项，请勿相加；旧任务未记录的部分不补估。</p>{groups.map(([name,metrics])=><section key={name}><h3>{names[name]||name}</h3><dl>{Object.entries(metrics as Record<string,Metric>).map(([key,row])=><div key={key} style={{display:'flex',justifyContent:'space-between',gap:'24px',padding:'8px 0'}}><dt>{labels[key]||key}{row.interrupted>0?' · 含中断':''}</dt><dd style={{margin:0,whiteSpace:'nowrap'}}>{duration(row.seconds)}</dd></div>)}</dl></section>)}</details>;
}
