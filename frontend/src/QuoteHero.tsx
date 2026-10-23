import {useEffect,useState} from 'react';
import quotes from './data/quotes.json';

function nextQuote(previous=-1){
 const exclude=previous>=0&&previous<quotes.length;
 let index=Math.floor(Math.random()*(quotes.length-(exclude?1:0)));
 if(exclude&&index>=previous)index++;
 return index;
}
export default function QuoteHero(){
 const [index,setIndex]=useState(()=>nextQuote(Number(sessionStorage.getItem('last-course-quote')??-1)));
 useEffect(()=>{sessionStorage.setItem('last-course-quote',String(index));},[index]);
 useEffect(()=>{const timer=setInterval(()=>setIndex(previous=>nextQuote(previous)),120000);return()=>clearInterval(timer);},[]);
 const quote=quotes[index];
 return <div className="quote-hero" data-quote-index={index}><h1 key={index}><button className="quote-refresh" title="点击换一句" aria-label={`换一句名言：${quote.text}`} onClick={()=>setIndex(previous=>nextQuote(previous))}>{quote.text}</button></h1><p>{quote.author}<span>《{quote.source}》</span></p></div>;
}
