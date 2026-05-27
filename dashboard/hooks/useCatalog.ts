import { useState, useCallback } from 'react'
import { authFetch } from '../lib/auth'
import type { CatalogItem, CatalogOption, Promotion, ErrorNotification } from '../lib/types'
import { addError } from '../lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'

export function useCatalog() {
  const [items, setItems] = useState<CatalogItem[]>([])
  const [options, setOptions] = useState<CatalogOption[]>([])
  const [promotions, setPromotions] = useState<Promotion[]>([])
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState<ErrorNotification[]>([])

  const loadItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await authFetch(`${API_URL}/api/catalog/items`)
      if (!res.ok) throw new Error(`Catalog items: ${res.status}`)
      setItems(await res.json())
    } catch (e: any) {
      setErrors(prev => addError(prev, e?.message || 'Error cargando items'))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadOptions = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/catalog/options`)
      if (!res.ok) throw new Error(`Options: ${res.status}`)
      setOptions(await res.json())
    } catch (e: any) {
      setErrors(prev => addError(prev, e?.message || 'Error cargando opciones'))
    }
  }, [])

  const loadPromotions = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/catalog/promotions`)
      if (!res.ok) throw new Error(`Promotions: ${res.status}`)
      setPromotions(await res.json())
    } catch (e: any) {
      setErrors(prev => addError(prev, e?.message || 'Error cargando promociones'))
    }
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    await Promise.all([loadItems(), loadOptions(), loadPromotions()])
    setLoading(false)
  }, [loadItems, loadOptions, loadPromotions])

  const createItem = useCallback(async (data: Partial<CatalogItem> & { key: string; name: string; price: number }) => {
    const res = await authFetch(`${API_URL}/api/catalog/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Create item: ${res.status}`)
    return res.json()
  }, [])

  const updateItem = useCallback(async (key: string, data: Partial<CatalogItem>) => {
    const res = await authFetch(`${API_URL}/api/catalog/items/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Update item: ${res.status}`)
    return res.json()
  }, [])

  const deleteItem = useCallback(async (key: string) => {
    const res = await authFetch(`${API_URL}/api/catalog/items/${key}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`Delete item: ${res.status}`)
  }, [])

  const createOption = useCallback(async (data: Partial<CatalogOption> & { key: string; name: string; price: number }) => {
    const res = await authFetch(`${API_URL}/api/catalog/options`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Create option: ${res.status}`)
    return res.json()
  }, [])

  const updateOption = useCallback(async (key: string, data: Partial<CatalogOption>) => {
    const res = await authFetch(`${API_URL}/api/catalog/options/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Update option: ${res.status}`)
    return res.json()
  }, [])

  const deleteOption = useCallback(async (key: string) => {
    const res = await authFetch(`${API_URL}/api/catalog/options/${key}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`Delete option: ${res.status}`)
  }, [])

  const createPromotion = useCallback(async (data: Partial<Promotion> & { key: string; name: string }) => {
    const res = await authFetch(`${API_URL}/api/catalog/promotions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Create promotion: ${res.status}`)
    return res.json()
  }, [])

  const updatePromotion = useCallback(async (key: string, data: Partial<Promotion>) => {
    const res = await authFetch(`${API_URL}/api/catalog/promotions/${key}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(`Update promotion: ${res.status}`)
    return res.json()
  }, [])

  const deletePromotion = useCallback(async (key: string) => {
    const res = await authFetch(`${API_URL}/api/catalog/promotions/${key}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`Delete promotion: ${res.status}`)
  }, [])

  const bulkImport = useCallback(async (data: any, clear: boolean = false) => {
    const res = await authFetch(`${API_URL}/api/catalog/bulk-import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data, clear }),
    })
    if (!res.ok) throw new Error(`Bulk import: ${res.status}`)
    return res.json()
  }, [])

  const reloadCatalog = useCallback(async () => {
    const res = await authFetch(`${API_URL}/api/catalog/reload`, { method: 'POST' })
    if (!res.ok) throw new Error(`Reload: ${res.status}`)
    return res.json()
  }, [])

  return {
    items, options, promotions, loading, errors,
    loadItems, loadOptions, loadPromotions, loadAll,
    createItem, updateItem, deleteItem,
    createOption, updateOption, deleteOption,
    createPromotion, updatePromotion, deletePromotion,
    bulkImport, reloadCatalog,
  }
}
