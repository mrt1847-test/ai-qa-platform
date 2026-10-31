// Static files only. No model, device, database or mutation API.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const port = Number(process.env.QA_DEMO_PORT || 8765);
const allowed = {'/':'index.html','/index.html':'index.html','/styles.css':'styles.css','/demo-data.js':'demo-data.js','/app.js':'app.js'};
const mime = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'};
const server = http.createServer((req,res)=>{
  if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
  let url;try{url=new URL(req.url,'http://127.0.0.1');}catch{res.writeHead(400);res.end();return;}
  const file=allowed[url.pathname];
  if(!file){res.writeHead(404,{'Content-Type':'text/plain; charset=utf-8'});res.end('Not found');return;}
  fs.readFile(path.join(__dirname,file),(err,data)=>{
    if(err){res.writeHead(500);res.end('Unable to read sample file');return;}
    res.writeHead(200,{'Content-Type':mime[path.extname(file)],'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"});
    res.end(req.method==='HEAD'?undefined:data);
  });
});
server.on('error',err=>{console.error(err.code==='EADDRINUSE'?`Port ${port} is already in use. Open the existing sample or set QA_DEMO_PORT to another port.`:err.message);process.exitCode=1;});
server.listen(port,'127.0.0.1',()=>{
  const url=`http://127.0.0.1:${port}`;
  console.log(`QA Studio interactive sample: ${url}`);
  console.log('Local static preview only. Press Ctrl+C to stop.');
  if(process.argv.includes('--open')){
    if(process.platform==='win32')spawn('rundll32.exe',['url.dll,FileProtocolHandler',url],{detached:true,stdio:'ignore',windowsHide:true}).unref();
  }
});
