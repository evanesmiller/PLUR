import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import Landing from './pages/Landing.jsx'
import ProjectDetail from './pages/ProjectDetail.jsx'
import NewProject from './pages/NewProject.jsx'

const router = createBrowserRouter([
  { path: '/', element: <Landing /> },
  { path: '/projects/new', element: <NewProject /> },
  { path: '/projects/:id', element: <ProjectDetail /> },
])

export default function App() {
  return <RouterProvider router={router} />
}
