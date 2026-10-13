
'use strict';
const loginForm=document.getElementById('mobile-login-form');
loginForm.addEventListener('submit',async event=>{
  event.preventDefault();
  const button=loginForm.querySelector('button');
  const error=document.getElementById('login-error');
  button.disabled=true;error.textContent='';
  try{
    const response=await fetch('/acceso',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body:new URLSearchParams(new FormData(loginForm)).toString()});
    if(response.ok){loginForm.reset();location.replace('/');return;}
    error.textContent=response.status===429?'Demasiados intentos. Espera cinco minutos.':response.status===401?'La contraseña no es correcta.':'No se ha podido entrar. Recarga la página y vuelve a intentarlo.';
  }catch(_){error.textContent='No se puede conectar con el Mac. Comprueba la Wi-Fi y que Videoteca siga abierta.';}
  finally{button.disabled=false;}
});
