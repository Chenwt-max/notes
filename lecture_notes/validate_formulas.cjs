const path = require('path');
const katex = require(path.join(__dirname, '../frontend/node_modules/katex'));
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const results = JSON.parse(input).map(row => {
    try {
      if (row.latex.length > 20000) throw Error('公式过长，需要对照原图检查');
      if (!row.latex.trim()) throw Error('公式不能为空');
      katex.renderToString(row.latex, {throwOnError:true, strict:'ignore', trust:false, maxExpand:1000});
      return {id:row.id, error:null};
    } catch (error) {
      return {id:row.id, error:String(error.message).slice(0,300)};
    }
  });
  process.stdout.write(JSON.stringify(results));
});
