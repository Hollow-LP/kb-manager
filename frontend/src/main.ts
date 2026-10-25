import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import { createApp } from 'vue'

import App from './App.vue'
import { setupPermissionDirective } from './directives/permission'
import router from './router'
import { pinia } from './stores'
import './styles/main.css'

const app = createApp(App)
app.use(pinia).use(router).use(ElementPlus, { locale: zhCn })
setupPermissionDirective(app)
app.mount('#app')
