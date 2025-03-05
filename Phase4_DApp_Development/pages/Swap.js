//صفحات رابط کاربری (UI Pages) در مسیر:   pages مسیر
//اگر بخواهید صفحه جدیدی مانند صفحه سواپ توکن اضافه کنید، فایل زیر را ایجاد کنید:
import React, { useState } from 'react'
import {
    Container,
    VStack,
    Box,
    Select,
    Input,
    Button,
    Text,
    Heading,
    HStack,
    IconButton
} from '@chakra-ui/react'
import Header from '../components/Header'
import { ArrowDownIcon } from '@chakra-ui/icons'

// این داده‌ها بعداً از اسمارت کانترکت خوانده می‌شوند
const mockTokens = [
    { symbol: 'ETH', name: 'Ethereum' },
    { symbol: 'USDT', name: 'Tether' },
    { symbol: 'DAI', name: 'Dai' }
]

export default function Swap() {
    const [fromToken, setFromToken] = useState('')
    const [toToken, setToToken] = useState('')
    const [amount, setAmount] = useState('')

    const handleSwap = () => {
        // اینجا منطق سوآپ توکن‌ها پیاده‌سازی می‌شود
        console.log('Swapping tokens...')
    }

    return (
        <>
            <Header />
            <Container maxW="container.sm" py={10}>
                <VStack spacing={8}>
                    <Heading>سوآپ توکن</Heading>

                    <Box width="full" p={6} borderWidth="1px" borderRadius="xl">
                        <VStack spacing={4}>
                            <Box width="full">
                                <Text mb={2}>از:</Text>
                                <HStack>
                                    <Input
                                        type="number"
                                        placeholder="مقدار"
                                        value={amount}
                                        onChange={(e) => setAmount(e.target.value)}
                                    />
                                    <Select
                                        placeholder="انتخاب توکن"
                                        value={fromToken}
                                        onChange={(e) => setFromToken(e.target.value)}
                                    >
                                        {mockTokens.map(token => (
                                            <option key={token.symbol} value={token.symbol}>
                                                {token.symbol} - {token.name}
                                            </option>
                                        ))}
                                    </Select>
                                </HStack>
                            </Box>

                            <IconButton
                                icon={<ArrowDownIcon />}
                                aria-label="تعویض توکن‌ها"
                                onClick={() => {
                                    const temp = fromToken
                                    setFromToken(toToken)
                                    setToToken(temp)
                                }}
                            />

                            <Box width="full">
                                <Text mb={2}>به:</Text>
                                <Select
                                    placeholder="انتخاب توکن"
                                    value={toToken}
                                    onChange={(e) => setToToken(e.target.value)}
                                >
                                    {mockTokens.map(token => (
                                        <option key={token.symbol} value={token.symbol}>
                                            {token.symbol} - {token.name}
                                        </option>
                                    ))}
                                </Select>
                            </Box>

                            <Button
                                colorScheme="blue"
                                width="full"
                                onClick={handleSwap}
                                isDisabled={!fromToken || !toToken || !amount}
                            >
                                سوآپ
                            </Button>
                        </VStack>
                    </Box>
                </VStack>
            </Container>
        </>
    )
}
