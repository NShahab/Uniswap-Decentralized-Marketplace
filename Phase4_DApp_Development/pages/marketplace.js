import React from 'react'
import {
    Container,
    SimpleGrid,
    Box,
    Image,
    Text,
    Button,
    VStack,
    Heading
} from '@chakra-ui/react'
import Header from '../components/Header'

// این داده‌ها بعداً از اسمارت کانترکت خوانده می‌شوند
const mockTokens = [
    {
        id: 1,
        name: 'توکن A',
        symbol: 'TKA',
        price: '0.1 ETH',
        image: 'https://via.placeholder.com/150'
    },
    {
        id: 2,
        name: 'توکن B',
        symbol: 'TKB',
        price: '0.2 ETH',
        image: 'https://via.placeholder.com/150'
    },
    // می‌توانید توکن‌های بیشتری اضافه کنید
]

export default function Marketplace() {
    return (
        <>
            <Header />
            <Container maxW="container.xl" py={10}>
                <VStack spacing={8} align="stretch">
                    <Heading>مارکت‌پلیس توکن‌ها</Heading>

                    <SimpleGrid columns={[1, 2, 3, 4]} spacing={6}>
                        {mockTokens.map(token => (
                            <Box
                                key={token.id}
                                borderWidth="1px"
                                borderRadius="lg"
                                overflow="hidden"
                                p={4}
                            >
                                <Image
                                    src={token.image}
                                    alt={token.name}
                                    borderRadius="md"
                                />
                                <VStack mt={4} align="start">
                                    <Text fontWeight="bold">{token.name}</Text>
                                    <Text color="gray.500">{token.symbol}</Text>
                                    <Text>{token.price}</Text>
                                    <Button colorScheme="blue" size="sm" width="full">
                                        خرید
                                    </Button>
                                </VStack>
                            </Box>
                        ))}
                    </SimpleGrid>
                </VStack>
            </Container>
        </>
    )
} 