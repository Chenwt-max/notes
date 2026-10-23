import {BookOpen,ChevronRight} from 'lucide-react';
import DeleteButton from './DeleteButton';

type Job=Record<string,any>;
export default function JobList({jobs,labels,open,remove}:{jobs:Job[];labels:Record<string,string>;open:(id:string)=>void;remove:(id:string)=>Promise<void>}){
 return <div className="job-list">{jobs.map(job=><div className="job-row" key={job.id}><button className="job-open" disabled={job.status==='delete_requested'} onClick={()=>open(job.id)}><span className="course-symbol"><BookOpen size={20}/></span><span className="job-copy"><b>{job.spec.title}</b><small>{job.status==='delete_failed'?job.error:job.stage+' · '+job.message}</small></span><span className={`status ${job.status}`}>{labels[job.status]||job.status}</span><ChevronRight size={17}/></button><DeleteButton label={`删除笔记：${job.spec.title}`} disabled={job.status==='delete_requested'} remove={()=>remove(job.id)}/></div>)}</div>;
}
